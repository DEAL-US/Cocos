"""What the registry is: its VoID description.

The VoID description is part of the registry graph, so it can be queried like the rest; it is a
void:Dataset, not a step or model, so the data flow and the discovery do not see it. Its numbers
(triples, classes, entities...) are counted on the registry without the description itself.
"""
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, XSD

from ..namespaces import COCOS, FORMATS, PREFIXES, SCHEMA, VOID, bind_prefixes

REGISTRY = COCOS['registry/']
# VoID asks for a dump other than the IRI of the dataset, which gives a page to browsers.
REGISTRY_DUMP = COCOS['registry.ttl']
SPARQL_ENDPOINT = COCOS['sparql']
# The registry copies labels of EDAM, which is CC BY-SA 4.0 (like terms.ttl).
REGISTRY_LICENSE = URIRef('https://creativecommons.org/licenses/by-sa/4.0/')
PUBLISHER = URIRef('https://deal.us.es')
NOT_LISTED = (COCOS, RDF, RDFS, OWL, XSD)  # as vocabularies of the registry


def dataset_description(registry):
    """The VoID description of `registry` (a graph of the steps, models, vocabulary and terms)."""
    graph = bind_prefixes(Graph())
    graph.add((REGISTRY, RDF.type, VOID.Dataset))
    graph.add((REGISTRY, DCTERMS.title, Literal('Cocos registry', lang='en')))
    graph.add((REGISTRY, DCTERMS.description, Literal(
        'The processing steps and antimicrobial resistance prediction models Cocos offers, what they '
        'consume and produce, the AMRF vocabulary and the reused ontology terms they use. The data of '
        'the users is not part of it.', lang='en')))
    graph.add((REGISTRY, DCTERMS.license, REGISTRY_LICENSE))
    graph.add((REGISTRY, DCTERMS.publisher, PUBLISHER))
    graph.add((REGISTRY, VOID.sparqlEndpoint, SPARQL_ENDPOINT))
    graph.add((REGISTRY, VOID.dataDump, REGISTRY_DUMP))
    graph.add((REGISTRY, VOID.uriSpace, Literal(str(COCOS))))
    for rdf_format in (FORMATS.Turtle, FORMATS['JSON-LD']):  # what its IRIs give RDF clients
        graph.add((REGISTRY, VOID.feature, rdf_format))
    for model in sorted(registry.subjects(RDF.type, SCHEMA.SoftwareApplication)):
        if str(model).startswith(str(COCOS['model/'])):
            graph.add((REGISTRY, VOID.exampleResource, model))
    for vocabulary in sorted(_vocabularies(registry)):
        graph.add((REGISTRY, VOID.vocabulary, URIRef(vocabulary)))
    entities = {s for s in registry.subjects() if isinstance(s, URIRef) and str(s).startswith(str(COCOS))}
    counts = {
        VOID.triples: len(registry),
        VOID.entities: len(entities),
        VOID.classes: len(set(registry.objects(None, RDF.type))),
        VOID.properties: len(set(registry.predicates())),
    }
    for predicate, count in counts.items():
        graph.add((REGISTRY, predicate, Literal(count)))
    return graph


def _vocabularies(registry):
    """The namespaces (of PREFIXES) of the terms `registry` uses, but its own and those of RDF itself
    (VoID asks for the vocabularies useful to query a dataset). Terms are counted anywhere in a
    triple, since the EDAM data and formats, ARO antibiotics and NCBITaxon organisms, classes of
    their ontologies, are values (schema:additionalType, schema:encodingFormat...)."""
    terms = {node for triple in registry for node in triple if isinstance(node, URIRef)}
    namespaces = sorted((str(namespace) for namespace in PREFIXES.values() if namespace not in NOT_LISTED),
                        key=len, reverse=True)
    return {next((ns for ns in namespaces if str(term).startswith(ns)), None) for term in terms} - {None}
