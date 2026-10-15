"""RDF namespaces used by the semantic layer.

COCOS reuses existing ontologies wherever a term exists and only defines its own terms in the
AMRF vocabulary (AntiMicrobial Resistance Framework) when none fits.
"""
from rdflib import Namespace
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

# Own vocabulary and the resources of this COCOS instance (steps, models, samples).
AMRF = Namespace('https://w3id.org/amrf/')
COCOS = Namespace('https://w3id.org/cocos/')

# Reused ontologies.
EDAM = Namespace('http://edamontology.org/')
SCHEMA = Namespace('https://schema.org/')
# Bioschemas types (FormalParameter...) and properties (input, output) live in different paths.
BIOSCHEMAS = Namespace('https://bioschemas.org/')
BSC = Namespace('https://bioschemas.org/properties/')
# OBO Foundry ontologies: ARO (antibiotics), NCBITaxon (organisms), IAO, NCIT...
OBO = Namespace('http://purl.obolibrary.org/obo/')
VANN = Namespace('http://purl.org/vocab/vann/')

PREFIXES = {
    'amrf': AMRF,
    'cocos': COCOS,
    'edam': EDAM,
    'schema': SCHEMA,
    'bioschemas': BIOSCHEMAS,
    'bsc': BSC,
    'obo': OBO,
    'vann': VANN,
    'dcterms': DCTERMS,
    'owl': OWL,
    'rdf': RDF,
    'rdfs': RDFS,
    'skos': SKOS,
    'xsd': XSD,
}


def bind_prefixes(graph):
    """Bind the COCOS prefixes so serialized graphs use them."""
    for prefix, namespace in PREFIXES.items():
        graph.bind(prefix, namespace, override=True, replace=True)
    return graph
