"""RDF description of a sample: a process, its organism and the data it has.

It is generated on demand from the database and never stored. The sample is a schema:Dataset;
each piece of data is a schema:DataDownload part: a file read in the role it plays in a step,
described with the same terms as the ports of the steps and models (EDAM data and format), so
that what a sample has can be compared with what a model consumes. A file can be two pieces of
data: a Bakta JSON is both the annotation and, once extracted, the genes.

The sample has the files the user uploaded and the outputs of its completed tasks.
"""
from dataclasses import dataclass

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from core.models import TaskStatus
from core.steps import UnknownStepError

from .mappings import data_term, format_term, sequencing_technique
from .namespaces import OBO, SCHEMA, bind_prefixes


@dataclass(frozen=True)
class DataEntry:
    """A file of the sample in one role, with what it holds."""
    file: object
    role: str
    data: URIRef
    format: URIRef
    technique: URIRef | None


def taxon_iri(curie):
    """obo:NCBITaxon_562 for 'NCBITaxon:562'."""
    return OBO[curie.replace(':', '_')]


def data_entries(process):
    """The data a process has: inputs uploaded by the user and outputs of completed tasks."""
    uploaded_nodes = {node['id'] for node in process.plan if not node['after']}
    entries = {}
    for task in process.tasks.prefetch_related('task_inputs__file', 'task_outputs__file').order_by('id'):
        try:
            step = task.get_step()
        except UnknownStepError:
            # e.g. a prediction with a model that is no longer registered
            continue
        links = []
        if task.plan_node in uploaded_nodes:
            links += [(link, step.input_port(link.role), sequencing_technique(step)) for link in task.task_inputs.all()]
        if task.status == TaskStatus.COMPLETED:
            links += [(link, step.output_port(link.role), None) for link in task.task_outputs.all()]
        for link, port, technique in links:
            entry = DataEntry(link.file, link.role, data_term(port.kind), format_term(port.kind, port.format), technique)
            entries.setdefault((link.file.pk, link.role), entry)
    return list(entries.values())


def entry_iri(sample, entry):
    return URIRef(f'{sample}#file-{entry.file.pk}-{entry.role}')


def sample_graph(process, sample_iri, content_url=None):
    """Return the RDF description of `process`, identified by `sample_iri`.

    `content_url(file)`, if given, returns the URL to download a file of the sample.
    """
    graph = bind_prefixes(Graph())
    sample = URIRef(sample_iri)
    graph.add((sample, RDF.type, SCHEMA.Dataset))
    graph.add((sample, SCHEMA.identifier, Literal(str(process.pk))))
    graph.add((sample, SCHEMA.name, Literal(process.name)))
    if process.organism:
        graph.add((sample, SCHEMA.taxonomicRange, taxon_iri(process.organism)))

    for entry in data_entries(process):
        node = entry_iri(sample, entry)
        graph.add((sample, SCHEMA.hasPart, node))
        graph.add((node, RDF.type, SCHEMA.DataDownload))
        graph.add((node, SCHEMA.identifier, Literal(str(entry.file.pk))))
        graph.add((node, SCHEMA.name, Literal(entry.role)))
        graph.add((node, SCHEMA.additionalType, entry.data))
        graph.add((node, SCHEMA.encodingFormat, entry.format))
        if entry.technique is not None:
            graph.add((node, SCHEMA.measurementTechnique, entry.technique))
        if content_url is not None:
            graph.add((node, SCHEMA.contentUrl, URIRef(content_url(entry.file))))
    return graph
