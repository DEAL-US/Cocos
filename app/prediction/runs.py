"""Prediction runs: one request that predicts with several models, each model as its own task."""
import logging

from django.db import transaction

from core.models import TaskStatus
from notifications.services import notify_user_conversion_complete, notify_user_conversion_failed

from .models import PredictionRun
from .prediction import NO_RESULT, create_prediction_csv, prepare_prediction_csv

logger = logging.getLogger(__name__)

FINISHED = (TaskStatus.COMPLETED, TaskStatus.FAILED)


def mark_run_started(run_id):
    with transaction.atomic():
        run = PredictionRun.objects.select_for_update().get(pk=run_id)
        if run.status == TaskStatus.PENDING:
            run.status = TaskStatus.RUNNING
            run.save(update_fields=['status', 'updated_at'])


def finish_run_if_done(run_id, last_task):
    """When every model task of the run has finished, build the matrix and the CSV and notify the user.

    Models that failed, or could not predict an antibiotic, appear as NO_RESULT.
    """
    with transaction.atomic():
        run = PredictionRun.objects.select_for_update().get(pk=run_id)
        tasks = list(run.tasks.all())
        if run.status in FINISHED or any(task.status not in FINISHED for task in tasks):
            return False

        results_by_model = {task.get_step().model_name: task.results for task in tasks}
        matrix = {
            'models': run.selected_models,
            'antibiotics': run.selected_antibiotics,
            'data': [
                [results_by_model.get(model, {}).get(antibiotic, NO_RESULT) for model in run.selected_models]
                for antibiotic in run.selected_antibiotics
            ],
        }
        try:
            models, rows = prepare_prediction_csv(matrix)
            run.output_csv = create_prediction_csv(run, models, rows)
            run.data = matrix['data']
            run.status = TaskStatus.COMPLETED
        except Exception:
            logger.exception("Could not build the results of prediction run %s", run.pk)
            run.status = TaskStatus.FAILED
        run.save()

    user = run.process.user
    if run.status == TaskStatus.COMPLETED:
        notify_user_conversion_complete(user, last_task, "The prediction task has completed successfully. You can now access your results.")
    else:
        notify_user_conversion_failed(user, last_task, "The prediction task has failed. Please try again.")
    return True
