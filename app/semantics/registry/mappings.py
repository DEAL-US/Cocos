"""How the terms of the code (data kinds, file types, step categories) translate to ontology terms.

The steps of the framework are described from the code with these tables; models and parsers
are described by hand in their descriptors.
"""
from core.models import File
from core.steps import DataKind

from ..namespaces import AMRF, EDAM, OBO

DATA = {
    DataKind.READS: EDAM.data_3494,                  # DNA sequence (EDAM has no "sequencing reads")
    DataKind.ASSEMBLY: EDAM.data_0925,               # Sequence assembly
    DataKind.ANNOTATED_GENOME: EDAM.data_1270,       # Feature table
    DataKind.GENE_SET: EDAM.data_0916,               # Gene report
    DataKind.RESISTANCE_PREDICTION: EDAM.data_2048,  # Report
}

FORMATS = {
    File.FileType.FASTQ: EDAM.format_1930,
    File.FileType.FASTA: EDAM.format_1929,
    File.FileType.JSON: EDAM.format_3464,
    File.FileType.CSV: EDAM.format_3752,
}

# Formats more specific than the file type for some kinds of data. Every annotation COCOS
# produces is written by Bakta.
SPECIFIC_FORMATS = {
    (DataKind.ANNOTATED_GENOME, File.FileType.JSON): AMRF.BaktaJSON,
}

OPERATIONS = {
    'assembly': EDAM.operation_0525,     # Genome assembly
    'annotation': EDAM.operation_0362,   # Genome annotation
    'extraction': EDAM.operation_1812,   # Data parsing
    'prediction': EDAM.operation_3482,   # Antimicrobial resistance prediction
}

SEQUENCING_TECHNIQUES = {
    'illumina': OBO.NCIT_C146817,        # Illumina Sequencing
    'ont': OBO.NCIT_C146818,             # Nanopore Sequencing
}


def data_term(kind):
    return DATA[kind]


def format_term(kind, file_type):
    return SPECIFIC_FORMATS.get((kind, file_type)) or FORMATS[file_type]


def operation_terms(step):
    """EDAM operations a step performs; an assembly that also annotates performs both."""
    operations = [OPERATIONS[step.category]]
    if getattr(step, 'annotate', False):
        operations.append(OPERATIONS['annotation'])
    return operations


def sequencing_technique(step):
    """NCIT technique of the reads a step consumes, or None if it does not depend on one."""
    technology = getattr(step, 'technology', '')
    return SEQUENCING_TECHNIQUES[technology] if technology else None


def kind_of(data_iri):
    """The DataKind an EDAM data term stands for."""
    for kind, term in DATA.items():
        if term == data_iri:
            return kind
    raise KeyError(f'No data kind for {data_iri}')


def file_type_of(format_iri):
    """The File.FileType a format term is stored as."""
    for (_, file_type), term in SPECIFIC_FORMATS.items():
        if term == format_iri:
            return file_type
    for file_type, term in FORMATS.items():
        if term == format_iri:
            return file_type
    raise KeyError(f'No file type for {format_iri}')
