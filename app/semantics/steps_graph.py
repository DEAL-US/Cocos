"""RDF description of the steps of the framework, generated from the step registry.

Each step is a Bioschemas ComputationalTool: a schema:SoftwareApplication with the EDAM
operations it performs and its inputs and outputs as FormalParameters (EDAM data and format).
"""
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF

from .mappings import data_term, format_term, operation_terms, sequencing_technique
from .namespaces import BIOSCHEMAS, BSC, COCOS, SCHEMA, bind_prefixes

COMPUTATIONAL_TOOL_PROFILE = URIRef('https://bioschemas.org/profiles/ComputationalTool/1.0-RELEASE')
FORMAL_PARAMETER_PROFILE = URIRef('https://bioschemas.org/profiles/FormalParameter/1.0-RELEASE')


def step_iri(step):
    return COCOS[f'step/{step.key}']


def port_iri(resource, role):
    return URIRef(f'{resource}#{role}')


def describe_step(graph, step):
    """Add the description of `step` to `graph` and return its IRI."""
    step_node = step_iri(step)
    graph.add((step_node, RDF.type, SCHEMA.SoftwareApplication))
    graph.add((step_node, DCTERMS.conformsTo, COMPUTATIONAL_TOOL_PROFILE))
    graph.add((step_node, SCHEMA.identifier, Literal(step.key)))
    graph.add((step_node, SCHEMA.name, Literal(step.label, lang='en')))
    for operation in operation_terms(step):
        graph.add((step_node, SCHEMA.featureList, operation))

    technique = sequencing_technique(step)
    for predicate, ports in ((BSC.input, step.consumes), (BSC.output, step.produces)):
        for port in ports:
            port_node = port_iri(step_node, port.role)
            graph.add((step_node, predicate, port_node))
            graph.add((port_node, RDF.type, BIOSCHEMAS.FormalParameter))
            graph.add((port_node, DCTERMS.conformsTo, FORMAL_PARAMETER_PROFILE))
            graph.add((port_node, SCHEMA.name, Literal(port.role)))
            graph.add((port_node, SCHEMA.additionalType, data_term(port.kind)))
            graph.add((port_node, SCHEMA.encodingFormat, format_term(port.kind, port.format)))
            if technique is not None and predicate == BSC.input:
                graph.add((port_node, SCHEMA.measurementTechnique, technique))
    return step_node


def steps_graph(steps):
    """Return a graph describing `steps`."""
    graph = bind_prefixes(Graph())
    for step in steps:
        describe_step(graph, step)
    return graph
