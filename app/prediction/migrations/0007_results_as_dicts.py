from django.db import migrations


def _as_result(value):
    """A probability stored as a number becomes a result with that score (see prediction.results)."""
    return {'score': float(value)} if isinstance(value, (int, float)) else value


def results_as_dicts(apps, schema_editor):
    PredictionTask = apps.get_model('prediction', 'PredictionTask')
    for task in PredictionTask.objects.exclude(results={}):
        task.results = {antibiotic: _as_result(value) for antibiotic, value in task.results.items()}
        task.save(update_fields=['results'])

    PredictionRun = apps.get_model('prediction', 'PredictionRun')
    for run in PredictionRun.objects.exclude(data=None):
        run.data = [[_as_result(value) for value in row] for row in run.data]
        run.save(update_fields=['data'])


class Migration(migrations.Migration):
    """Results of predictions are dicts with a score and/or a call, no longer a bare probability."""

    dependencies = [
        ('prediction', '0006_remove_old_task_fields'),
    ]

    operations = [
        migrations.RunPython(results_as_dicts, migrations.RunPython.noop),
    ]
