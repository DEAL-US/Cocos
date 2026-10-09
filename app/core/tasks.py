"""Celery tasks that run one task of a process: run_step starts it and poll_step follows external jobs."""
import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.utils import timezone

from core.models import Task, TaskStatus
from core.steps import Busy, StepError
from notifications.services import (
    notify_user_conversion_complete,
    notify_user_conversion_failed,
    notify_user_conversion_started,
    notify_user_server_busy,
)

logger = logging.getLogger(__name__)

MAX_TRIES = 100
RETRY_DELAY = 60


def _get_task(task_id):
    task = Task.objects.select_related('process__user').filter(id=task_id).first()
    return task.concrete if task else None


def _label(task):
    return task.get_step().label


def start_task(task, job_id=None):
    task.status = TaskStatus.RUNNING
    task.started_at = timezone.now()
    task.external_job_id = job_id
    task.save(update_fields=['status', 'started_at', 'external_job_id', 'updated_at'])
    notify_user_conversion_started(
        task.process.user, task,
        f"The {_label(task)} for the process {task.process.name} has started and is now running.",
    )


def complete_task(task):
    task.status = TaskStatus.COMPLETED
    task.finished_at = timezone.now()
    task.save(update_fields=['status', 'finished_at', 'updated_at'])
    notify_user_conversion_complete(
        task.process.user, task,
        f"The {_label(task)} for the process {task.process.name} is complete. You can now access your results.",
    )


def fail_task(task, message):
    logger.error("Task %s (%s) failed: %s", task.id, task.step, message)
    task.status = TaskStatus.FAILED
    task.finished_at = timezone.now()
    task.save(update_fields=['status', 'finished_at', 'updated_at'])
    notify_user_conversion_failed(task.process.user, task, message)


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
            fail_task(task, str(error))
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
        fail_task(task, "External job failed")
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
