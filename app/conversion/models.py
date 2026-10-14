from django.db import models
from django.core.exceptions import ValidationError

from core.models import Task, TaskStatus

# CONVERSION TASK MODELS
class ConversionTask(Task):
    """A conversion task representing a bioinformatics process"""

    task_ptr = models.OneToOneField(Task, on_delete=models.CASCADE, parent_link=True, primary_key=True, db_column='id')

    # Model-level validation
    def clean(self):
        super().clean()
        # Tasks that run on an external service need its job id once they are running or completed
        needs_job = self.step and self.get_step().is_external
        if needs_job and not self.external_job_id and self.status not in (TaskStatus.PENDING, TaskStatus.FAILED):
            raise ValidationError({'external_job_id': 'external_job_id can be null only when status is "pending" or "failed".'})

    # Ensure model validation runs on save
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ConversionTask(external_job_id={self.external_job_id}, status={self.status}, step={self.step})"
    class Meta:
        db_table = 'converter_conversiontask'
