"""Conversion steps run on the bio service (assembly, annotation) or locally (gene extraction)."""
from core.models import File
from core.steps import DataKind, ExternalStep, LocalStep, Port, register_step

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


@register_step
class BaktaGeneExtraction(LocalStep):
    """Extract the genes of a Bakta JSON and link them to the file."""
    key = 'bakta_gene_extraction'
    label = 'Gene extraction'
    category = 'extraction'
    consumes = (Port('annotation', DataKind.ANNOTATED_GENOME, JSON),)
    produces = (Port('genes', DataKind.GENE_SET, JSON),)
    default_parameters = {'complete_version': False}
