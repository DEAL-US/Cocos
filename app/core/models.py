import os
import re

from django.db import models
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError

# TASKS
class TaskStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'

class Task(models.Model):
    """Base task shared by conversion and prediction tasks (multi-table inheritance)"""
    status = models.CharField(max_length=50, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    process = models.ForeignKey('ProcessGroup', on_delete=models.PROTECT, related_name='tasks')
    # Allow blank so we can create a pending task before an external job id exists.
    external_job_id = models.CharField(max_length=100, unique=True, null=True, blank=True)

    @property
    def concrete(self):
        """Return the child instance (ConversionTask, PredictionTask...) behind this task"""
        for rel in self._meta.related_objects:
            if not rel.parent_link:
                continue
            try:
                return getattr(self, rel.get_accessor_name())
            except ObjectDoesNotExist:
                continue
        return self

    def __str__(self):
        return f"Task(id={self.pk}, status={self.status})"
    class Meta:
        db_table = 'model_task'

# GENE AND RELATED MODELS
class GeneQuerySet(models.QuerySet):
    """Custom QuerySet for Gene model"""
    def search_identifiers(self, identifiers):
        """Search for genes containing any of the identifiers (case insensitive)"""
        queries = models.Q()
        for identifier in identifiers:
            esc = re.escape(identifier.strip())
            pattern = rf'(^|,\s*){esc}($|,)'
            queries |= models.Q(identifiers__iregex=pattern)
        return self.filter(queries)
    
class Gene(models.Model):
    """Gene with multiple identifiers"""
    identifiers = models.TextField()

    objects = GeneQuerySet.as_manager()

    def identifiers_list(self):
        """Return list of identifiers"""
        return [s.strip() for s in (self.identifiers or '').split(',') if s.strip()]

    def add_identifier(self, identifier):
        """Add an identifier if not already present"""
        identifier = identifier.strip()
        identifier_list = self.identifiers_list()
       
        if identifier not in identifier_list:
            identifier_list.append(identifier)
            self.identifiers = ', '.join(identifier_list)
            self.save(update_fields=['identifiers'])

    def add_identifiers(self, identifiers):
        """Add multiple identifiers if not already present"""
        for identifier in identifiers:
            self.add_identifier(identifier)

    def __str__(self):
        return self.identifiers
    class Meta:
        db_table = 'model_gene'
    
    
class FileGene(models.Model):
    """Through model linking File and Gene with expert info"""
    file = models.ForeignKey('File', on_delete=models.CASCADE)
    gene = models.ForeignKey(Gene, on_delete=models.CASCADE)
    expert = models.CharField(max_length=255)
    start = models.IntegerField(null=True, blank=True)
    stop = models.IntegerField(null=True, blank=True)
    nt = models.TextField(null=True, blank=True)
    aa = models.TextField(null=True, blank=True)

    def clean(self):
        if self.file and self.file.file_type != File.FileType.JSON:
            raise ValidationError({'file': 'Genes can only be linked to JSON files.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.file} - {self.gene} ({self.expert})"
    class Meta:
        db_table = 'model_filegene'

# FILE AND PROCESS GROUP MODELS
def get_file_upload_path(instance, filename):
    user_id = instance.user_id or 'unknown'
    file_type = instance.file_type or 'unknown'
    safe_name = os.path.basename(filename)
    return f"uploads/persistent/user_{user_id}/{file_type}/{safe_name}"

class File(models.Model):
    """File in the system"""
    class FileType(models.TextChoices):
        FASTQ = 'fastq', 'FASTQ'
        FASTA = 'fasta', 'FASTA'
        JSON = 'json', 'JSON'
        CSV = 'csv', 'CSV'

    created_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to=get_file_upload_path)
    file_type = models.CharField(max_length=50, choices=FileType.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='files')
    genes = models.ManyToManyField('Gene', related_name='files', blank=True, through='FileGene')

    def __str__(self):
        return f"File created at {self.created_at} by {self.user.username} ({self.file.name})"
    class Meta:
        db_table = 'model_file'

class ProcessGroup(models.Model):
    """Grouping of conversion tasks under a name"""
    name = models.CharField(max_length=255)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='process_groups')

    def __str__(self):
        return self.name
