"""Prediction runs: one request that predicts with several models, each model as its own task."""
import csv
import logging
from io import StringIO

from django.core.files.base import ContentFile
from django.db import transaction

from core.models import File, TaskStatus
from notifications.services import notify_user_conversion_complete, notify_user_conversion_failed

from .models import NO_RESULT, PredictionRun

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


# CSV of a run

def prepare_prediction_csv(matrix):
    if not isinstance(matrix, dict):
        raise ValueError('Invalid matrix payload.')

    models = matrix.get('models')
    antibiotics = matrix.get('antibiotics')
    data = matrix.get('data')

    if not all(isinstance(value, list) for value in [models, antibiotics, data]):
        raise ValueError('Invalid matrix structure.')

    if len(antibiotics) != len(data):
        raise ValueError('Matrix data size mismatch.')

    for row in data:
        if not isinstance(row, list) or len(row) != len(models):
            raise ValueError('Matrix rows must match models length.')

    rows = []

    for antibiotic, values in zip(antibiotics, data):
        row_values = []

        for value in values:
            if value in (None, NO_RESULT):
                row_values.append('')
                continue

            try:
                row_values.append(round(float(value), 4))
            except (ValueError, TypeError):
                row_values.append('')

        numeric_values = [value for value in row_values if value != '']

        average = (round(sum(numeric_values) / len(numeric_values), 4) if numeric_values else '')

        rows.append([antibiotic] + row_values + [average])

    return models, rows

def create_prediction_csv(task, models, rows):
    """Store the combined CSV of a prediction. `task` is a PredictionTask or a PredictionRun."""
    if not task:
        raise ValueError('Missing prediction task.')

    if not models:
        raise ValueError('Missing models.')

    if not rows:
        raise ValueError('Missing prediction rows.')

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(['Antibiotic', *models, 'Average'])
    writer.writerows(rows)

    csv_file = File(user=task.process.user, file_type=File.FileType.CSV)

    filename = f'prediction_{task.id}.csv'

    csv_file.file.save(filename, ContentFile(output.getvalue().encode('utf-8')), save=True)
    return csv_file
