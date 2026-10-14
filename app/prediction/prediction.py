import csv
from io import StringIO

from django.core.files.base import ContentFile

from .registry import get_model_adapter_class
from core.models import File

# Value stored for a model/antibiotic pair that could not be predicted.
NO_RESULT = 'NO_RESULT'

# Prediction functions

def get_prediction(model_name: str, antibiotic: str, file) -> float:
    model_cls = get_model_adapter_class(model_name)
    if not model_cls:
        raise ValueError(f'Model {model_name} not found in registry.')

    adapter = model_cls(antibiotic=antibiotic)

    adapter.load()
    return adapter.predict(file)


# CSV generation functions

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