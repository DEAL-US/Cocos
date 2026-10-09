"""Conversion steps run on the bio service (assembly, annotation) or locally (gene extraction).

There is one gene extraction step per registered parser that declares what it consumes.
"""
from core.models import File
from core.steps import DataKind, ExternalStep, LocalStep, Port, register_step, register_step_provider

from .parsers import PARSERS

FASTQ = File.FileType.FASTQ
FASTA = File.FileType.FASTA
JSON = File.FileType.JSON

ASSEMBLY_OUTPUT = Port('assembly', DataKind.ASSEMBLY, FASTA)
ANNOTATION_OUTPUT = Port('annotation', DataKind.ANNOTATED_GENOME, JSON)


class AssemblyStep(ExternalStep):
    """Assembly on the bio service. With `annotate`, the service also runs Bakta in the same job."""
    category = 'assembly'
    technology = ''
    annotate = False


@register_step
class AssemblyONT(AssemblyStep):
    key = 'assembly_ont'
    label = 'Assembly · ONT'
    technology = 'ont'
    consumes = (Port('reads', DataKind.READS, FASTQ),)
    produces = (ASSEMBLY_OUTPUT,)


@register_step
class AssemblyIllumina(AssemblyStep):
    key = 'assembly_illumina'
    label = 'Assembly · Illumina'
    technology = 'illumina'
    consumes = (Port('r1', DataKind.READS, FASTQ), Port('r2', DataKind.READS, FASTQ))
    produces = (ASSEMBLY_OUTPUT,)


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
class BaktaAnnotation(ExternalStep):
    """Bakta annotation of an assembly uploaded to the bio service."""
    key = 'bakta_annotation'
    label = 'Annotation'
    category = 'annotation'
    consumes = (Port('assembly', DataKind.ASSEMBLY, FASTA),)
    produces = (ANNOTATION_OUTPUT,)
    default_parameters = {'threads': 4}


GENE_EXTRACTION_STEP_PREFIX = 'extract_'


class GeneExtractionStep(LocalStep):
    """Extract the genes of an annotation with a registered parser and link them to the file."""
    category = 'extraction'

    def __init__(self, parser_name, parser):
        self.parser_name = parser_name
        self.key = f'{GENE_EXTRACTION_STEP_PREFIX}{parser_name}'
        self.label = f'Gene extraction · {parser.label}'
        self.consumes = (Port('annotation', parser.consumes_kind, parser.consumes_format),)
        # The genes are linked to the parsed file itself, so the output keeps its format.
        self.produces = (Port('genes', DataKind.GENE_SET, parser.consumes_format),)
        self.default_parameters = dict(parser.default_options)


@register_step_provider
def gene_extraction_steps():
    steps = (
        GeneExtractionStep(name, parser)
        for name, parser in PARSERS.items()
        if getattr(parser, 'consumes_kind', None) is not None
    )
    return {step.key: step for step in steps}
