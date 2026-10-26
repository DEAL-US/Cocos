"""Celery tasks that run one task of a process: run_step starts it and poll_step follows external jobs."""
import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.utils import timezone

# Module import: core.orchestration imports this module to launch tasks.
from core import orchestration
from core.models import Failure, Task, TaskStatus
from core.steps import Busy, StepError, cocos_software, get_step
from notifications.services import (
    notify_user_conversion_complete,
    notify_user_conversion_failed,
    notify_user_conversion_started,
    notify_user_conversion_warning,
    notify_user_server_busy,
)

logger = logging.getLogger(__name__)

MAX_TRIES = 100
RETRY_DELAY = 60


def _get_task(task_id):
    task = Task.objects.select_related('process__user').filter(id=task_id).first()
    return task.concrete if task else None


EXTRACTION_WARNING = ("Annotation succeeded, but automatic result upload failed. "
                      "Try uploading the Bakta JSON manually from your downloads.")


# --- Notifications: users are told when each request (a batch of plan nodes) starts and finishes,
# and about every failure. Tasks outside a plan count as a batch of their own.
def _batch(task):
    if not task.plan_node:
        return [], [task]
    nodes = orchestration.batch_nodes(task.process, task.plan_node)
    tasks_by_node = orchestration.latest_tasks(task.process)
    return nodes, [tasks_by_node[node['id']] for node in nodes if node['id'] in tasks_by_node]


def _batch_label(task, nodes):
    return get_step(nodes[0]['step']).label if nodes else task.get_step().label


def _is_prediction_batch(nodes):
    # A prediction request can start with preparation steps; its predictions have a run.
    return any('run' in node for node in nodes)


def _notify_started(task):
    nodes, tasks = _batch(task)
    if any(other.pk != task.pk and other.started_at for other in tasks):
        return
    if _is_prediction_batch(nodes):
        message = "The prediction task has started and is now running."
    else:
        message = f"The {_batch_label(task, nodes)} for the process {task.process.name} has started and is now running."
    notify_user_conversion_started(task.process.user, task, message)


def _notify_if_batch_done(task):
    nodes, tasks = _batch(task)
    if _is_prediction_batch(nodes):
        return  # prediction requests finish with their PredictionRun
    if nodes:
        tasks_by_node = {other.plan_node: other for other in tasks}
        done = all(
            node['id'] in tasks_by_node and (
                tasks_by_node[node['id']].status == TaskStatus.COMPLETED
                or orchestration.is_soft_failure(tasks_by_node[node['id']], node))
            for node in nodes
        )
        if not done:
            return
    notify_user_conversion_complete(
        task.process.user, task,
        f"The {_batch_label(task, nodes)} for the process {task.process.name} is complete. You can now access your results.",
    )


# --- Task lifecycle
def start_task(task, job_id=None):
    task.status = TaskStatus.RUNNING
    task.started_at = timezone.now()
    task.external_job_id = job_id
    task.save(update_fields=['status', 'started_at', 'external_job_id', 'updated_at'])
    _notify_started(task)
    task.get_step().on_task_started(task)


def record_software(task):
    """Keep the software the task used: Cocos, and what its step reports. A step that cannot
    report it (e.g. the bio service is unreachable) leaves only Cocos."""
    try:
        used = list(task.get_step().software(task))
    except Exception:
        logger.exception("Unable to get the software used by task %s (%s)", task.id, task.step)
        used = []
    task.software = [cocos_software()] + used


def complete_task(task):
    task.status = TaskStatus.COMPLETED
    task.finished_at = timezone.now()
    record_software(task)
    task.save(update_fields=['status', 'finished_at', 'software', 'updated_at'])
    _notify_if_batch_done(task)
    task.get_step().on_task_finished(task)
    if task.plan_node:
        orchestration.advance_plan(task.process)


def fail_task(task, message, permanent=False, error=None):
    """Mark `task` as failed and tell the user `message`. `error` (by default, the message) is
    kept with the task, and `permanent` says that running it again would fail again."""
    logger.error("Task %s (%s) failed: %s", task.id, task.step, error or message)
    task.status = TaskStatus.FAILED
    task.finished_at = timezone.now()
    task.error = error or message
    task.failure = Failure.PERMANENT if permanent else Failure.TRANSIENT
    record_software(task)
    task.save(update_fields=['status', 'finished_at', 'error', 'failure', 'software', 'updated_at'])
    if task.plan_node and orchestration.is_soft_failure(task, orchestration.find_node(task.process, task.plan_node)):
        notify_user_conversion_warning(task.process.user, task, EXTRACTION_WARNING)
        _notify_if_batch_done(task)
    else:
        notify_user_conversion_failed(task.process.user, task, message)
    task.get_step().on_task_finished(task)
    if task.plan_node:
        _cancel_blocked_nodes(task)


def _cancel_blocked_nodes(failed_task):
    """Cancel the nodes that can no longer run because `failed_task` failed (e.g. predictions after a
    failed preparation step). Other blocked nodes stay, so retrying the failed node continues the plan."""
    process = failed_task.process
    nodes = [node for node in orchestration.blocked_nodes(process, failed_task.plan_node)
             if get_step(node['step']).cancel_when_blocked]
    if not nodes:
        return
    orchestration.cancel_nodes(process, {node['id'] for node in nodes})
    for node in nodes:
        get_step(node['step']).on_node_cancelled(process, node, failed_task)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=1, max_retries=MAX_TRIES)
def run_step(self, task_id):
    """Start a pending task: run a local step, or submit an external job and start polling it."""
    task = _get_task(task_id)
    if task is None or task.status != TaskStatus.PENDING:
        logger.info("Task %s is not pending, nothing to run", task_id)
        return

    step = task.get_step()
    if not step.is_external:
        start_task(task)
        try:
            step.process(task)
        except StepError as error:
            fail_task(task, str(error), permanent=True)
        except Exception:
            logger.exception("Unexpected error running task %s (%s)", task.id, task.step)
            fail_task(task, f"Unexpected error in {step.label}. Try again later.")
        else:
            complete_task(task)
        return

    # Connection errors propagate and are retried by Celery.
    result = step.process(task)
    if isinstance(result, Busy):
        logger.info("Bio service busy for task %s, will retry later", task.id)
        try:
            self.retry(countdown=RETRY_DELAY)
        except MaxRetriesExceededError:
            logger.error("Max retries exhausted starting task %s", task.id)
            notify_user_server_busy(task.process.user, task)
        return

    start_task(task, job_id=result.job_id)
    poll_step.delay(task.id)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10, max_retries=MAX_TRIES)
def poll_step(self, task_id):
    """Follow the external job of a running task and collect its outputs when it finishes."""
    task = _get_task(task_id)
    if task is None or task.status != TaskStatus.RUNNING:
        logger.info("Task %s is not running, stopping poll", task_id)
        return

    step = task.get_step()
    external_status, code = step.job_status(task.external_job_id)

    if code == 404:
        fail_task(task, "External job not found")
        return

    status = step.task_status(external_status)

    if status == TaskStatus.FAILED:
        error, permanent = step.job_failure(task.external_job_id)
        fail_task(task, "External job failed", permanent=permanent, error=error)
        return

    if status == TaskStatus.COMPLETED:
        try:
            step.collect(task)
        except Exception:
            logger.exception("Unable to collect results of task %s, will retry", task.id)
            try:
                self.retry(countdown=RETRY_DELAY)
            except MaxRetriesExceededError:
                fail_task(task, "Max retries exceeded while collecting results")
            return
        complete_task(task)
        return

    try:
        self.retry(countdown=RETRY_DELAY)
    except MaxRetriesExceededError:
        fail_task(task, "Max retries exceeded while polling status")
