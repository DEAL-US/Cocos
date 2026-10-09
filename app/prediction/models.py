from django.db import models
from django.core.exceptions import ValidationError

from core.models import File, Task, TaskStatus


class PredictionRun(models.Model):
    """One prediction request: several models and antibiotics on the same genes.

    Each model runs as its own PredictionTask; the run combines their results in a matrix and a CSV.
    """
    process = models.ForeignKey('core.ProcessGroup', on_delete=models.PROTECT, related_name='prediction_runs')
    status = models.CharField(max_length=50, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    selected_models = models.JSONField(default=list)
    selected_antibiotics = models.JSONField(default=list)
    data = models.JSONField(default=list, blank=True, null=True)
    output_csv = models.ForeignKey('core.File', on_delete=models.PROTECT, null=True, blank=True, related_name='prediction_run_csv')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.output_csv and self.output_csv.file_type != File.FileType.CSV:
            raise ValidationError({'output_csv': 'Output CSV must be a CSV file.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"PredictionRun(id={self.pk}, status={self.status})"

    class Meta:
        db_table = 'model_predictionrun'


class PredictionTask(Task):
    """A prediction task representing a model prediction process"""

    task_ptr = models.OneToOneField(Task, on_delete=models.CASCADE, parent_link=True, primary_key=True, db_column='id')
    output_csv = models.ForeignKey('core.File', on_delete=models.PROTECT, null=True, blank=True, related_name='prediction_output_csv')

    # Old one-task-for-all-models fields, removed in the contract migration; new tasks leave them empty.
    selected_models = models.JSONField(default=list, blank=True)
    selected_antibiotics = models.JSONField(default=list, blank=True)
    data = models.JSONField(default=list, blank=True, null=True)

    # Null only while old prediction tasks (one task for all models) still exist.
    run = models.ForeignKey(PredictionRun, on_delete=models.CASCADE, null=True, blank=True, related_name='tasks')
    results = models.JSONField(default=dict, blank=True)

    # Model-level validation
    def clean(self):
        super().clean()
        if self.output_csv and self.output_csv.file_type != File.FileType.CSV:
            raise ValidationError({'output_csv': 'Output CSV must be a CSV file.'})

    # Ensure model validation runs on save
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
