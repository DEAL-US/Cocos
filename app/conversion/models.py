import re
from django.db import models
from django.core.exceptions import ValidationError

from core.models import File, Task, TaskStatus

# CONVERSION TASK MODELS
class ConversionTask(Task):
    """A conversion task representing a bioinformatics process"""

    class ConversionTaskType(models.TextChoices):
        ANNOTATION = 'annotation', 'Annotation'
        FROM_JSON = 'from_json', 'JSON Processing'
        ASSEMBLY_ONT = 'assembly_ont', 'ONT Assembly'
        ASSEMBLY_ILLUMINA = 'assembly_illumina', 'Illumina Assembly'
        ASSEMBLY_ONT_ANNOTATED = 'assembly_ont_annotated', 'ONT Assembly with Annotation'
        ASSEMBLY_ILLUMINA_ANNOTATED = 'assembly_illumina_annotated', 'Illumina Assembly with Annotation'
    
    task_ptr = models.OneToOneField(Task, on_delete=models.CASCADE, parent_link=True, primary_key=True, db_column='id')
    input_files = models.ManyToManyField(File, related_name='input_conversion_tasks', blank=True)
    output_files = models.ManyToManyField(File, related_name='output_conversion_tasks', blank=True)
    task_type = models.CharField(max_length=50, choices=ConversionTaskType.choices)

    # Model-level validation
    def clean(self):
        super().clean()
        # Check that external_job_id is not null when status is not 'pending'
        if not self.external_job_id and self.status != TaskStatus.PENDING and self.status != TaskStatus.FAILED and self.task_type not in [self.ConversionTaskType.FROM_JSON]:
            raise ValidationError({'external_job_id': 'external_job_id can be null only when status is "pending" or "failed".'})

    # Ensure model validation runs on save
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ConversionTask(external_job_id={self.external_job_id}, status={self.status}, task_type={self.task_type})"
    class Meta:
        db_table = 'converter_conversiontask'
