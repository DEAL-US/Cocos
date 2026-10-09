from django.db import models
from django.core.exceptions import ValidationError

from core.models import File, Task

class PredictionTask(Task):
    """A prediction task representing a model prediction process"""

    task_ptr = models.OneToOneField(Task, on_delete=models.CASCADE, parent_link=True, primary_key=True, db_column='id')
    output_csv = models.ForeignKey('core.File', on_delete=models.PROTECT, null=True, blank=True, related_name='prediction_output_csv')

    selected_models = models.JSONField(default=list)
    selected_antibiotics = models.JSONField(default=list)
    data = models.JSONField(default=list, blank=True, null=True)

    # Model-level validation
    def clean(self):
        super().clean()
        if self.output_csv and self.output_csv.file_type != File.FileType.CSV:
            raise ValidationError({'output_csv': 'Output CSV must be a CSV file.'})

    # Ensure model validation runs on save
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)