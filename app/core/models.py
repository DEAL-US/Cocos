import os
import re

from django.db import models
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.files.base import ContentFile
from django.core.validators import RegexValidator

from core.steps import UnknownStepError, get_step
from core.utils import upload_file

# TASKS
class TaskStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'

class Task(models.Model):
    """Base task shared by conversion and prediction tasks (multi-table inheritance).

    A task is one execution of a step (see core.steps): `step` is the step key, and the
    files it consumes and produces are linked with their role through TaskInput/TaskOutput.
    """
    status = models.CharField(max_length=50, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    process = models.ForeignKey('ProcessGroup', on_delete=models.PROTECT, related_name='tasks')
    # Allow blank so we can create a pending task before an external job id exists.
    external_job_id = models.CharField(max_length=100, unique=True, null=True, blank=True)

    step = models.CharField(max_length=100, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    plan_node = models.CharField(max_length=100, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    tool_version = models.CharField(max_length=100, blank=True)

    inputs = models.ManyToManyField('File', through='TaskInput', related_name='consumed_by_tasks', blank=True)
    outputs = models.ManyToManyField('File', through='TaskOutput', related_name='produced_by_tasks', blank=True)

    def clean(self):
        super().clean()
        if self.step:
            try:
                get_step(self.step)
            except UnknownStepError:
                raise ValidationError({'step': f'Unknown step: {self.step}'})

    def get_step(self):
        """Return the step this task executes."""
        return get_step(self.step)

    # --- Files by role
    def add_input(self, role, file):
        return TaskInput.objects.create(task=self, file=file, role=role)

    def add_output(self, role, file):
        return TaskOutput.objects.create(task=self, file=file, role=role)

    def save_output(self, role, content, file_type, filename):
        """Store `content` as a new file of the process owner and link it as an output."""
        file = upload_file(ContentFile(content, name=filename), self.process.user, file_type)
        self.add_output(role, file)
        return file

    def input_file(self, role):
        return _linked_file(self.task_inputs, role, self, 'input')

    def output_file(self, role):
        return _linked_file(self.task_outputs, role, self, 'output')

    def read_input(self, role):
        with self.input_file(role).file.open('rb') as f:
            return f.read()

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


def _linked_file(links, role, task, direction):
    link = links.select_related('file').filter(role=role).first()
    if link is None:
        raise ObjectDoesNotExist(f"Task {task.pk} has no {direction} with role {role!r}")
    return link.file


class TaskFileLink(models.Model):
    """A file consumed or produced by a task, with the role it plays in the task's step."""
    role = models.CharField(max_length=100)

    def _port(self):
        step = self.task.get_step()
        return step.input_port(self.role) if self.direction == 'input' else step.output_port(self.role)

    def clean(self):
        super().clean()
        if not self.task.step:
            return
        try:
            port = self._port()
        except KeyError:
            raise ValidationError({'role': f"Step {self.task.step} has no {self.direction} {self.role!r}"})
        if port.format and self.file.file_type != port.format:
            raise ValidationError({'file': f"{self.direction.capitalize()} {self.role!r} must be a {port.format} file"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.task} {self.direction} {self.role}: {self.file}"

    class Meta:
        abstract = True


class TaskInput(TaskFileLink):
    direction = 'input'
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='task_inputs')
    file = models.ForeignKey('File', on_delete=models.CASCADE, related_name='task_inputs')

    class Meta:
        db_table = 'model_taskinput'
        constraints = [models.UniqueConstraint(fields=['task', 'role'], name='unique_task_input_role')]


class TaskOutput(TaskFileLink):
    direction = 'output'
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='task_outputs')
    file = models.ForeignKey('File', on_delete=models.CASCADE, related_name='task_outputs')

    class Meta:
        db_table = 'model_taskoutput'
        constraints = [models.UniqueConstraint(fields=['task', 'role'], name='unique_task_output_role')]

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

NCBI_TAXON_CURIE = RegexValidator(r'^NCBITaxon:\d+$', 'Use an NCBI Taxonomy CURIE such as NCBITaxon:562.')

class ProcessGroup(models.Model):
    """Grouping of the tasks run on a sample under a name.

    `plan` lists the steps to run as nodes {'id', 'step', 'parameters', 'after': [node ids]}.
    """
    name = models.CharField(max_length=255)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='process_groups')
    # Blank means other / unknown. The organisms offered to users come from the prediction models.
    organism = models.CharField(max_length=32, blank=True, default='', validators=[NCBI_TAXON_CURIE])
    plan = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name
