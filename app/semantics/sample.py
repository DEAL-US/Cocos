"""RDF description of a sample: a process, its organism and the data it has.

It is generated on demand from the database and never stored. The sample is a schema:Dataset;
each piece of data is a schema:DataDownload part: a file read in the role it plays in a step,
described with the same terms as the ports of the steps and models (EDAM data and format), so
that what a sample has can be compared with what a model consumes. A file can be two pieces of
data: a Bakta JSON is both the annotation and, once extracted, the genes. The genes are kept in the
database of Cocos, linked to that file, so they have no file format, checksum or download link.
Files have their SHA-256 (schema:sha256), to check that a file is the one described.

The sample has the files the user uploaded and the outputs of its completed tasks. On request, the
description also has the provenance of that data (semantics.provenance).
"""
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from core.models import TaskStatus
from core.steps import UnknownStepError

from .namespaces import OBO, SCHEMA, bind_prefixes
from .provenance import add_provenance
from .registry.mappings import data_term, format_term, sequencing_technique


def taxon_iri(curie):
    """obo:NCBITaxon_562 for 'NCBITaxon:562'."""
    return OBO[curie.replace(':', '_')]


def data_entries(process):
    """The data a process has, as (file, role, port, sequencing technique or None) tuples: the inputs
    uploaded by the user and the outputs of completed tasks, once per file and role."""
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
            entries.setdefault((link.file.pk, link.role), (link.file, link.role, port, technique))
    return list(entries.values())


def sample_graph(process, sample_iri, content_url=None, with_provenance=False):
    """Return the RDF description of `process`, identified by `sample_iri`.

    `content_url(file)`, if given, returns the URL to download a file of the sample. With
    `with_provenance`, the description also says how its data was obtained (PROV-O).
    """
    graph = bind_prefixes(Graph())
    sample = URIRef(sample_iri)
    graph.add((sample, RDF.type, SCHEMA.Dataset))
    graph.add((sample, SCHEMA.identifier, Literal(str(process.pk))))
    graph.add((sample, SCHEMA.name, Literal(process.name)))
    if process.organism:
        graph.add((sample, SCHEMA.taxonomicRange, taxon_iri(process.organism)))

    entries = {}
    for file, role, port, technique in data_entries(process):
        node = URIRef(f'{sample}#file-{file.pk}-{role}')
        entries[(file.pk, role)] = node
        graph.add((sample, SCHEMA.hasPart, node))
        graph.add((node, RDF.type, SCHEMA.DataDownload))
        graph.add((node, SCHEMA.identifier, Literal(str(file.pk))))
        graph.add((node, SCHEMA.name, Literal(role)))
        graph.add((node, SCHEMA.additionalType, data_term(port.kind)))
        file_format = format_term(port.kind, port.format)
        if technique is not None:
            graph.add((node, SCHEMA.measurementTechnique, technique))
        # Data Cocos stores itself (the genes) has no format and is not downloaded as that file
        if file_format is not None:
            graph.add((node, SCHEMA.encodingFormat, file_format))
            if file.sha256:
                graph.add((node, SCHEMA.sha256, Literal(file.sha256)))
            if content_url is not None:
                graph.add((node, SCHEMA.contentUrl, URIRef(content_url(file))))

    if with_provenance:
        add_provenance(graph, process, sample, entries)
    return graph
