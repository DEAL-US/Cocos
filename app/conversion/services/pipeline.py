import os

from ..models import ConversionTask
from core.models import File, TaskStatus
from core.orchestration import create_process, extend_plan, latest_tasks, retry_node
from .presentation import format_process_label
from core.utils import upload_file
from prediction.adapters.registry import list_all_organisms

ASSEMBLY_STEPS = {
    'illumina': 'assembly_illumina',
    'ont': 'assembly_ont',
}

GENE_EXTRACTION_STEP = 'extract_bakta_json'


def _extraction_node(node_id, after, complete_version):
    return {'id': node_id, 'step': GENE_EXTRACTION_STEP, 'after': after,
            'parameters': {'complete_version': complete_version}}


def _check_organism(organism):
    """The organism of a new process: blank (other / unknown) or one offered by the prediction models."""
    if organism and organism not in dict(list_all_organisms()):
        raise ValueError('Unknown organism.')
    return organism


def _next_node_ids(process, count):
    """Ids for new plan nodes, following the existing n1, n2... numbering."""
    first = len(process.plan) + 1
    return [f'n{first + offset}' for offset in range(count)]


def _annotations_of(process):
    """Annotation tasks of a process (the latest one of each plan node)."""
    return [task for task in latest_tasks(process).values() if task.step == 'bakta_annotation']


def get_assembly_tasks_can_be_annotated(user):
    """Return completed assembly jobs whose FASTA has not been annotated."""

    assembly_tasks = (
        ConversionTask.objects
        .filter(process__user=user, status=TaskStatus.COMPLETED, step__in=ASSEMBLY_STEPS.values())
        .select_related('process')
        .order_by('-updated_at', '-id')
    )

    available = []
    for task in assembly_tasks:
        if any(annotation.status != TaskStatus.FAILED for annotation in _annotations_of(task.process)):
            continue

        output_file = task.task_outputs.filter(role='assembly').select_related('file').first()
        task.source_filename = (os.path.basename(output_file.file.file.name) if output_file else 'Assembly output')
        task.source_label = format_process_label(task)
        available.append(task)

    return available


# Assembly
def start_assembly(user, assembly_type, fastq, fastq_2=None, annotate=False, complete_version=False, organism=''):

    organism = _check_organism(organism)

    if assembly_type not in ASSEMBLY_STEPS:
        raise ValueError("Invalid assembly type.")

    if not fastq:
        raise ValueError("No FASTQ file uploaded.")

    if assembly_type == "illumina" and not fastq_2:
        raise ValueError("Illumina assembly requires a second FASTQ file.")

    if assembly_type == "ont" and fastq_2:
        raise ValueError("Second FASTQ file is only valid for Illumina assembly.")

    file_1 = upload_file(fastq, user=user, file_type=File.FileType.FASTQ)
    if assembly_type == "illumina":
        file_2 = upload_file(fastq_2, user=user, file_type=File.FileType.FASTQ)
        reads = {'r1': file_1, 'r2': file_2}
    else:
        reads = {'reads': file_1}

    step = ASSEMBLY_STEPS[assembly_type]
    if annotate:
        nodes = [{'id': 'n1', 'step': f'{step}_annotated'}, _extraction_node('n2', ['n1'], complete_version)]
    else:
        nodes = [{'id': 'n1', 'step': step}]

    return create_process(user, os.path.basename(fastq.name), nodes, {'n1': reads}, organism=organism)


# Annotation
def retry_assembly(process):
    """Run the failed assembly of a process again with the same reads; what was planned after it follows."""
    failed = [task for task in latest_tasks(process).values()
              if task.get_step().category == 'assembly' and task.status == TaskStatus.FAILED]
    if not failed:
        raise ValueError('This process has no failed assembly to retry.')
    retry_node(process, failed[0].plan_node)


def start_annotation_from_assembly_task(user, source_task_id, complete_version):
    source_task = ConversionTask.objects.filter(
        process__user=user,
        id=source_task_id,
        status=TaskStatus.COMPLETED,
        step__in=ASSEMBLY_STEPS.values(),
    ).select_related('process').first()

    if not source_task:
        raise ValueError('Selected assembly result is not available for annotation.')

    process = source_task.process
    annotations = _annotations_of(process)

    if any(annotation.status != TaskStatus.FAILED for annotation in annotations):
        raise ValueError('This assembly result already has an annotation task.')

    if annotations:
        # Retry the failed annotation with the same assembly; its gene extraction is already planned.
        retry_node(process, annotations[0].plan_node)
        return process

    annotation_id, extraction_id = _next_node_ids(process, 2)
    extend_plan(process, [
        {'id': annotation_id, 'step': 'bakta_annotation', 'after': [source_task.plan_node]},
        _extraction_node(extraction_id, [annotation_id], complete_version),
    ])
    return process

def start_annotation_from_uploaded_fasta(user, fasta, complete_version, organism=''):
    organism = _check_organism(organism)

    if not fasta:
        raise ValueError('No FASTA file uploaded for annotation.')

    file = upload_file(fasta, user=user, file_type=File.FileType.FASTA)

    nodes = [{'id': 'n1', 'step': 'bakta_annotation'}, _extraction_node('n2', ['n1'], complete_version)]
    return create_process(user, os.path.basename(file.file.name), nodes, {'n1': {'assembly': file}}, organism=organism)

# JSON Parsing
def start_json_processing(user, feature_file, complete_version=False, organism=''):
    organism = _check_organism(organism)

    if not feature_file:
        raise ValueError('Select a JSON file.')

    file = upload_file(feature_file, user=user, file_type=File.FileType.JSON)

    nodes = [_extraction_node('n1', [], complete_version)]
    return create_process(user, os.path.basename(file.file.name), nodes, {'n1': {'annotation': file}}, organism=organism)
