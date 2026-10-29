import os
from django.db.models import Max, Prefetch, Q
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone

from ..models import ConversionTask
from prediction.adapters.registry import list_all_organisms
from prediction.models import PredictionRun
from prediction.services import prediction_trust
from core.models import Failure, File, ProcessGroup, TaskInput, TaskOutput, TaskStatus
from core.steps import used_software_labels
from ..steps import GENE_EXTRACTION_STEP_PREFIX
from .presentation import status_badge_class, build_process_steps, format_duration
from core.pagination import get_pagination_page_range

READ_ROLES = ('reads', 'r1', 'r2')


def _conversion_tasks():
    """Conversion tasks with their input and output files, newest first."""
    return (
        ConversionTask.objects
        .prefetch_related(
            Prefetch('task_inputs', queryset=TaskInput.objects.select_related('file')),
            Prefetch('task_outputs', queryset=TaskOutput.objects.select_related('file')),
        )
        .order_by('-updated_at', '-id')
    )


def get_processes_of_user_prefetch_tasks_and_files(user):
    """
    Return a queryset of ProcessGroup objects for the given user,
    with prefetching of related ConversionTask objects and related File objects.
    The queryset is ordered by the last updated time of the tasks in descending order.
    """
    return (
        ProcessGroup.objects.filter(user=user)
        .annotate(last_updated=Max('tasks__updated_at', filter=Q(tasks__conversiontask__isnull=False)))
        .prefetch_related(Prefetch('tasks', queryset=_conversion_tasks(), to_attr='list_tasks'))
        .order_by('-last_updated', '-id')
    )


def _linked_file(links, role):
    return next((link.file for link in links.all() if link.role == role), None)


class _ProcessTasks:
    """The conversion tasks of a process as the pages show them.

    A gene extraction that follows another step (an annotation, or an assembly that also
    annotates) is not shown on its own: that step is shown as running until its genes are
    extracted. An extraction that fails after the annotation only warns, so the step is
    shown as completed.
    """

    def __init__(self, process, tasks):
        self.process = process
        self.tasks = tasks
        self._nodes = {node['id']: node for node in process.plan}
        self._latest = {}
        for task in tasks:
            self._latest.setdefault(task.plan_node, task)
        self._extraction_after = {
            dependency: node['id']
            for node in process.plan if node['step'].startswith(GENE_EXTRACTION_STEP_PREFIX)
            for dependency in node['after']
        }
        self.visible = [task for task in tasks if not self._is_folded(task)]

    def _is_folded(self, task):
        node = self._nodes.get(task.plan_node)
        return task.get_step().category == 'extraction' and bool(node and node['after'])

    def _extraction(self, task):
        node_id = self._extraction_after.get(task.plan_node)
        return node_id, self._latest.get(node_id)

    def status(self, task):
        if task.status != TaskStatus.COMPLETED:
            return task.status
        node_id, extraction = self._extraction(task)
        if node_id is None:
            return TaskStatus.COMPLETED
        if extraction is None or extraction.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return TaskStatus.RUNNING
        return TaskStatus.COMPLETED

    def updated_at(self, task):
        _, extraction = self._extraction(task)
        return max(task.updated_at, extraction.updated_at) if extraction else task.updated_at

    def finished_at(self, task):
        """When the shown step finished: with its gene extraction, if it has one."""
        _, extraction = self._extraction(task)
        if task.status == TaskStatus.COMPLETED and extraction:
            return extraction.finished_at
        return task.finished_at

    def genes_found(self, task):
        """How many genes the gene extraction of the shown step found, or None if none has finished."""
        _, extraction = self._extraction(task)
        extraction = extraction or task
        if extraction.get_step().category != 'extraction' or extraction.status != TaskStatus.COMPLETED:
            return None
        return extraction.output_file('genes').genes.count()

    def latest(self, category):
        """The most recently updated shown task of the given step category."""
        return next((task for task in self.visible if task.get_step().category == category), None)

    def all(self, category):
        return [task for task in self.visible if task.get_step().category == category]

    def extracted_without_genes(self):
        """Whether a completed gene extraction of the process found no genes."""
        return any(
            task.status == TaskStatus.COMPLETED and not task.output_file('genes').genes.exists()
            for task in self._latest.values() if task.get_step().category == 'extraction'
        )


def _input_filename(task, roles):
    names = [os.path.basename(file.file.name) for file in (_linked_file(task.task_inputs, role) for role in roles) if file]
    return ", ".join(names)


def build_process_rows(user):
    """
    Build a list of process rows for the given user, each containing relevant
    information about the process and its tasks reasy for the task list view.
    """
    processes = get_processes_of_user_prefetch_tasks_and_files(user)
    rows = []

    for process in processes:
        view = _ProcessTasks(process, process.list_tasks)

        if view.all('assembly'):
            rows.append(_build_assembly_row(view))

        elif view.all('annotation'):
            rows.append(_build_annotation_row(view))

        elif view.all('extraction'):
            rows.append(_build_json_row(view))

    rows.sort(
        key=lambda row: (row['updated_at'], row['task'].id),
        reverse=True,
    )

    return rows

def _build_assembly_row(view):
    """Build a process row for an assembly task."""

    assembly_task = view.latest('assembly')
    latest_annotation = view.latest('annotation')
    assembly_step = assembly_task.get_step()

    auto_annotated = assembly_step.annotate
    annotation_started = bool(latest_annotation) or auto_annotated
    assembly_status = view.status(assembly_task)
    annotation_status = view.status(latest_annotation) if latest_annotation else None

    if latest_annotation:
        top_pipeline = 'Annotation'
        top_status = annotation_status
    else:
        top_pipeline = assembly_step.label
        top_status = assembly_status

    most_recent = view.updated_at(latest_annotation) if latest_annotation else view.updated_at(assembly_task)

    assembly_completed = assembly_status == TaskStatus.COMPLETED

    has_auto_json = auto_annotated and assembly_completed

    input_filename = _input_filename(assembly_task, READ_ROLES)

    can_annotate = assembly_completed and not latest_annotation and not auto_annotated
    can_retry_annotation = annotation_status == TaskStatus.FAILED and not auto_annotated
    # The FASTA can be downloaded as soon as it is saved, even while its genes are being extracted.
    has_fasta = _linked_file(assembly_task.task_outputs, 'assembly') is not None
    has_json = annotation_status == TaskStatus.COMPLETED or has_auto_json

    stage_class = ("process-stage-max" if has_json else "process-stage-mid" if annotation_started else "process-stage-light")

    return {
        'kind': 'assembly',
        'process_name': view.process.name,
        'pipeline_type': assembly_step.label,
        'status': top_status,
        'status_badge': status_badge_class(top_status),
        'top_pipeline': top_pipeline,
        'input_filename': input_filename,
        'updated_at': most_recent,
        'task': assembly_task,
        'annotation_started': annotation_started,
        'can_annotate': can_annotate,
        'can_retry_annotation': can_retry_annotation,
        'has_fasta': has_fasta,
        'has_json': has_json,
        'is_auto_annotated': auto_annotated,
        'steps': build_process_steps(assembly_status=assembly_status, annotation_status=annotation_status, is_auto_annotated=auto_annotated),
        'stage_class': stage_class,
    }

def _build_annotation_row(view):
    """Build a process row for an annotation task."""

    latest = view.latest('annotation')
    status = view.status(latest)
    uploaded_fasta = _linked_file(latest.task_inputs, 'assembly')
    annotation_json = _linked_file(latest.task_outputs, 'annotation')

    stage_class = ("process-stage-max" if status == TaskStatus.COMPLETED else "process-stage-mid")

    return {
        'kind': 'annotation',
        'process_name': view.process.name,
        'pipeline_type': latest.get_step().label,
        'status': status,
        'status_badge': status_badge_class(status),
        'input_filename': os.path.basename(uploaded_fasta.file.name) if uploaded_fasta else '',
        'updated_at': view.updated_at(latest),
        'task': latest,
        'can_annotate': False,
        'can_retry_annotation': False,
        'has_fasta': bool(uploaded_fasta),
        'has_json': bool(annotation_json),
        'steps': build_process_steps(annotation_status=status),
        'stage_class': stage_class,
    }

def _build_json_row(view):
    """Build a process row for an uploaded JSON."""

    latest = view.latest('extraction')
    status = view.status(latest)
    json_upload = _linked_file(latest.task_inputs, 'annotation')

    stage_class = ("process-stage-max" if status == TaskStatus.COMPLETED else "process-stage-dark")

    return {
        'kind': 'json',
        'process_name': view.process.name,
        'pipeline_type': latest.get_step().label,
        'status': status,
        'status_badge': status_badge_class(status),
        'input_filename': os.path.basename(json_upload.file.name) if json_upload else '',
        'updated_at': view.updated_at(latest),
        'task': latest,
        'can_annotate': False,
        'can_retry_annotation': False,
        'has_fasta': False,
        'has_json': bool(json_upload),
        'steps': build_process_steps(json_status=status),
        'stage_class': stage_class,
    }


def build_process_status_context(process, page=1):
    """Build the context for the process status template."""

    view = _ProcessTasks(process, list(_conversion_tasks().filter(process=process)))
    shown = view.visible

    latest_task = shown[0]
    first_task = shown[-1]

    assembly_task = view.latest('assembly')
    latest_annotation = view.latest('annotation')
    latest_json = view.latest('extraction')

    is_auto_annotated = bool(assembly_task and assembly_task.get_step().annotate)

    has_completed_assembly = (assembly_task and view.status(assembly_task) == TaskStatus.COMPLETED)

    can_annotate = (has_completed_assembly and latest_annotation is None and not is_auto_annotated)

    can_retry_annotation = (has_completed_assembly and latest_annotation is not None
        and view.status(latest_annotation) == TaskStatus.FAILED and not is_auto_annotated)

    can_retry_assembly = bool(assembly_task and view.status(assembly_task) == TaskStatus.FAILED)

    process_kind = ('assembly' if assembly_task else 'json' if latest_json else 'annotation')

    pipeline_badges = [task.get_step().label for task in (assembly_task, latest_annotation, latest_json) if task]

    timeline = [_build_timeline_entry(view, task) for task in reversed(shown)]

    prediction_runs = list(PredictionRun.objects
        .filter(process=process)
        .order_by('-created_at', '-id')
    )

    paginator = Paginator(prediction_runs, 3)
    prediction_page = paginator.get_page(page)

    pagination_url = reverse('conversion:process_status', kwargs={'process_id': process.id})

    pagination_page_range = get_pagination_page_range(paginator, prediction_page.number)

    trust = prediction_trust(process, list(prediction_page))
    predictions = [
        {
            'id': run.id,
            'status': run.status,
            'status_badge': status_badge_class(run.status),
            'created_at': run.created_at,
            'updated_at': run.updated_at,
            'models': run.selected_models,
            'antibiotics': run.selected_antibiotics,
            'matrix': {
                'models': run.selected_models,
                'antibiotics': run.selected_antibiotics,
                'data': run.data,
                # How much each result can be trusted, in the same order as `data` (None: no result)
                'trust': [[trust.get(run.id, {}).get(model, {}).get(antibiotic) for model in run.selected_models]
                          for antibiotic in run.selected_antibiotics],
            },
            'matrix_json_id': f'prediction-matrix-{run.id}',
            'can_download': (
                run.status == TaskStatus.COMPLETED
                and run.output_csv is not None
            ),
        }
        for run in prediction_page
    ]

    latest_status = view.status(latest_task)
    # The organisms Cocos knows something about (declared by the models, or in their data).
    organism_options = list_all_organisms()

    return {
        'process_name': process.name,
        'process_id': process.id,
        'organism': process.organism,
        'organism_name': dict(organism_options).get(process.organism, process.organism),
        'organism_options': organism_options,
        'process_kind': process_kind,
        'pipeline_badges': pipeline_badges,
        'latest_task_status': latest_status,
        'status_badge': status_badge_class(latest_status),
        'last_updated': view.updated_at(latest_task),
        'created_at': first_task.created_at,
        'fasta_download_task_id': _get_fasta_download_task_id(view, assembly_task, latest_annotation),
        'json_download_task_id': _get_json_download_task_id(view, assembly_task, latest_annotation, latest_json, is_auto_annotated),
        'can_annotate': can_annotate,
        'can_retry_annotation': can_retry_annotation,
        'can_retry_assembly': can_retry_assembly,
        'extracted_without_genes': view.extracted_without_genes(),
        'timeline': timeline,
        'assembly_task_id': assembly_task.id if assembly_task else None,
        'predictions': predictions,
        'page_obj': prediction_page,
        'pagination_page_range': pagination_page_range,
        'pagination_url': pagination_url,
        'pagination_query': '',
        'pagination_label': 'Predictions',
        'pagination_link_attribute': 'data-prediction-page',
    }

def _get_fasta_download_task_id(view, assembly_task, latest_annotation):
    if assembly_task and _linked_file(assembly_task.task_outputs, 'assembly'):
        return assembly_task.id

    if latest_annotation:
        return latest_annotation.id

    return None

def _get_json_download_task_id(view, assembly_task, latest_annotation, latest_json, is_auto_annotated):
    if latest_annotation and _linked_file(latest_annotation.task_outputs, 'annotation'):
        return latest_annotation.id

    if is_auto_annotated and assembly_task and view.status(assembly_task) == TaskStatus.COMPLETED:
        return assembly_task.id

    if latest_json and view.status(latest_json) == TaskStatus.COMPLETED:
        if _linked_file(latest_json.task_inputs, 'annotation'):
            return latest_json.id

    return None

def _build_timeline_entry(view, task):
    """Build a timeline entry representing a conversion task: when it ran, what it used and
    produced, and why it failed, if it did."""

    status = view.status(task)
    finished_at = view.finished_at(task)
    if status == TaskStatus.RUNNING and task.started_at:
        duration = format_duration(task.started_at, timezone.now())
    elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED) and task.started_at and finished_at:
        duration = format_duration(task.started_at, finished_at)
    else:
        duration = None

    return {
        'label': task.get_step().label,
        'status': status,
        'status_badge': status_badge_class(status),
        'started_at': task.started_at,
        'updated_at': view.updated_at(task),
        'duration': duration,
        'inputs': _data_filenames(task.task_inputs),
        # The genes are counted, not listed: their file is internal to Cocos.
        'outputs': _data_filenames(task.task_outputs, exclude_roles=('genes',)),
        'genes_found': view.genes_found(task),
        'error': task.error if status == TaskStatus.FAILED else '',
        'may_work_again': task.failure != Failure.PERMANENT,
        'software': used_software_labels(task),
    }


def _data_filenames(links, exclude_roles=()):
    """The names of the sequence and annotation files linked to a task, by role (r1 before r2)."""
    return [
        os.path.basename(link.file.file.name)
        for link in sorted(links.all(), key=lambda link: link.role)
        if link.role not in exclude_roles
        and link.file.file_type in (File.FileType.FASTQ, File.FileType.FASTA, File.FileType.JSON)
    ]



def rename_process(process, new_name):
    process.name = new_name
    process.save(update_fields=["name"])

def set_process_organism(process, organism):
    """Set the organism of a process: blank (other / unknown) or one Cocos knows (list_all_organisms).

    Earlier predictions keep their results; what can run on the sample is decided with the new one.
    """
    if organism and organism not in dict(list_all_organisms()):
        raise ValueError('Unknown organism.')
    process.organism = organism
    process.save(update_fields=['organism'])

def get_process_files(process):
    """Files consumed or produced by the tasks of a process."""
    return File.objects.filter(Q(task_inputs__task__process=process) | Q(task_outputs__task__process=process)).distinct()

def get_fastq_uploads_for_task(task):
    """Return FASTQ file(s) object for a task, or None if not found."""
    return File.objects.filter(task_inputs__task=task, task_inputs__role__in=READ_ROLES).order_by('task_inputs__role')

def get_fasta_upload_for_task(task):
    """Return FASTA file object for a task, or None if not found."""
    category = task.get_step().category

    if category == 'annotation':
        return _linked_file(task.task_inputs, 'assembly')

    if category == 'assembly':
        return _linked_file(task.task_outputs, 'assembly')

    return None


def get_json_upload_for_task(task):
    """Return the JSON File object for a task, or None if not found."""
    step = task.get_step()

    if step.category == 'annotation' or (step.category == 'assembly' and step.annotate):
        return _linked_file(task.task_outputs, 'annotation')

    if step.category == 'extraction':
        return _linked_file(task.task_inputs, 'annotation')

    return None
