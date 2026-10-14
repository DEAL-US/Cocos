"""Conversion steps run on the bio service (assembly, annotation) or locally (gene extraction).

There is one gene extraction step per registered parser that declares what it consumes.
"""
import json
import os

from core.models import File, TaskStatus
from core.steps import Busy, DataKind, ExternalStep, LocalStep, Port, Started, StepError, register_step, register_step_provider
from notifications.services import notify_user_conversion_warning

from . import bio_api_client
from .models import ConversionTask
from .parsers import PARSERS, parse_file

FASTQ = File.FileType.FASTQ
FASTA = File.FileType.FASTA
JSON = File.FileType.JSON

ASSEMBLY_OUTPUT = Port('assembly', DataKind.ASSEMBLY, FASTA)
ANNOTATION_OUTPUT = Port('annotation', DataKind.ANNOTATED_GENOME, JSON)

# Statuses the bio service answers when it accepts a job; anything else (e.g. 'busy') means try later.
ACCEPTED_STATUSES = {'pending', 'running', 'annotation_pending'}


def _submission_result(response):
    if response.get('status') in ACCEPTED_STATUSES and response.get('job_id'):
        return Started(response['job_id'])
    return Busy()


class BioServiceStep(ExternalStep):
    """A step run as a job in the bio service."""
    task_model = ConversionTask

    def job_status(self, job_id):
        return bio_api_client.get_job_status(job_id)

    def _already_saved(self, task, role):
        # collect() may be retried after a partial failure: keep what was already stored.
        return task.task_outputs.filter(role=role).exists()

    def save_assembly(self, task):
        if self._already_saved(task, 'assembly'):
            return
        content = bio_api_client.download_assembly_fasta_result(task.external_job_id)
        if not content:
            raise ValueError('Downloaded FASTA content is empty')
        filename = f"assembly_{task.external_job_id}.fasta"
        task.save_output('assembly', content, FASTA, filename)

    def save_annotation(self, task):
        if self._already_saved(task, 'annotation'):
            return
        payload = bio_api_client.download_bakta_json_result(task.external_job_id)
        if isinstance(payload, list):
            payload = {'features': payload}
        elif not isinstance(payload, dict):
            raise ValueError('Downloaded annotation payload has invalid format')
        filename = f"annotation_{task.external_job_id}.json"
        task.save_output('annotation', json.dumps(payload).encode('utf-8'), JSON, filename)


class AssemblyStep(BioServiceStep):
    """Assembly on the bio service. With `annotate`, the service also runs Bakta in the same job."""
    category = 'assembly'
    technology = ''
    annotate = False

    @property
    def finished_status(self):
        # With auto-annotation the job reports 'assembled' first and only finishes when annotated.
        return 'annotated' if self.annotate else 'assembled'

    def collect(self, task):
        self.save_assembly(task)
        if self.annotate:
            self.save_annotation(task)


@register_step
class AssemblyONT(AssemblyStep):
    key = 'assembly_ont'
    label = 'Assembly · ONT'
    technology = 'ont'
    consumes = (Port('reads', DataKind.READS, FASTQ),)
    produces = (ASSEMBLY_OUTPUT,)

    def process(self, task):
        return _submission_result(bio_api_client.sequence_ont(task.read_input('reads'), annotate=self.annotate))


@register_step
class AssemblyIllumina(AssemblyStep):
    key = 'assembly_illumina'
    label = 'Assembly · Illumina'
    technology = 'illumina'
    consumes = (Port('r1', DataKind.READS, FASTQ), Port('r2', DataKind.READS, FASTQ))
    produces = (ASSEMBLY_OUTPUT,)

    def process(self, task):
        response = bio_api_client.sequence_illumina(task.read_input('r1'), task.read_input('r2'), annotate=self.annotate)
        return _submission_result(response)


@register_step
class AssemblyONTAnnotated(AssemblyONT):
    key = 'assembly_ont_annotated'
    label = 'Assembly + Annotation · ONT'
    annotate = True
    produces = (ASSEMBLY_OUTPUT, ANNOTATION_OUTPUT)


@register_step
class AssemblyIlluminaAnnotated(AssemblyIllumina):
    key = 'assembly_illumina_annotated'
    label = 'Assembly + Annotation · Illumina'
    annotate = True
    produces = (ASSEMBLY_OUTPUT, ANNOTATION_OUTPUT)


@register_step
class BaktaAnnotation(BioServiceStep):
    """Bakta annotation of an assembly uploaded to the bio service."""
    key = 'bakta_annotation'
    label = 'Annotation'
    category = 'annotation'
    finished_status = 'annotated'
    consumes = (Port('assembly', DataKind.ASSEMBLY, FASTA),)
    produces = (ANNOTATION_OUTPUT,)
    default_parameters = {'threads': 4}

    def process(self, task):
        response = bio_api_client.annotate_from_fasta(task.read_input('assembly'), threads=task.parameters['threads'])
        return _submission_result(response)

    def collect(self, task):
        self.save_annotation(task)


GENE_EXTRACTION_STEP_PREFIX = 'extract_'


class GeneExtractionStep(LocalStep):
    """Extract the genes of an annotation with a registered parser and link them to the file."""
    category = 'extraction'
    task_model = ConversionTask

    def __init__(self, parser_name, parser):
        self.parser_name = parser_name
        self.key = f'{GENE_EXTRACTION_STEP_PREFIX}{parser_name}'
        self.label = f'Gene extraction · {parser.label}'
        self.consumes = (Port('annotation', parser.consumes_kind, parser.consumes_format),)
        self.produces = (Port('genes', DataKind.GENE_SET, parser.consumes_format),)
        self.default_parameters = dict(parser.default_options)

    def process(self, task):
        file = task.input_file('annotation')
        try:
            data = PARSERS[self.parser_name].read(file)
        except ValueError:
            raise StepError('Error decoding JSON file.')
        try:
            parse_file(self.parser_name, data, file, user=task.process.user, options=task.parameters)
        except Exception:
            raise StepError('Error parsing features. Try again later.')
        # The genes are linked to the annotation file itself.
        task.add_output('genes', file)

    def on_task_finished(self, task):
        if task.status != TaskStatus.COMPLETED:
            return
        file = task.output_file('genes')
        if not file.genes.exists():
            notify_user_conversion_warning(
                task.process.user, task,
                f"No genes were found in {os.path.basename(file.file.name)}, so it cannot be used for predictions.",
            )


@register_step_provider
def gene_extraction_steps():
    steps = (
        GeneExtractionStep(name, parser)
        for name, parser in PARSERS.items()
        if getattr(parser, 'consumes_kind', None) is not None
    )
    return {step.key: step for step in steps}
