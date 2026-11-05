"""RDF namespaces used by the semantic layer.

Cocos reuses existing ontologies wherever a term exists and only defines its own terms in the
AMRF vocabulary (AntiMicrobial Resistance Framework) when none fits.
"""
from rdflib import Namespace
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS, VOID, XSD

# Own vocabulary and the resources of this Cocos instance (steps, models, samples).
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

# What something is about (IAO 'is about'): e.g. the antibiotic of a measurement, a file or a result
IS_ABOUT = OBO.IAO_0000136
VANN = Namespace('http://purl.org/vocab/vann/')
# Provenance: PROV-O (W3C) and P-Plan, its extension for the plans that activities follow.
PPLAN = Namespace('http://purl.org/net/p-plan#')
# Quality of a plug-in (W3C Data Quality Vocabulary): measurements such as its F1 score.
DQV = Namespace('http://www.w3.org/ns/dqv#')
# Web Annotation (W3C), which DQV uses for quality annotations: the trust of a prediction.
OA = Namespace('http://www.w3.org/ns/oa#')
# What the registry is (VoID, imported above) and what the SPARQL endpoint offers (SPARQL 1.1
# Service Description, with the W3C IRIs of media types).
SD = Namespace('http://www.w3.org/ns/sparql-service-description#')
FORMATS = Namespace('http://www.w3.org/ns/formats/')

PREFIXES = {
    'amrf': AMRF,
    'cocos': COCOS,
    'edam': EDAM,
    'schema': SCHEMA,
    'bioschemas': BIOSCHEMAS,
    'bsc': BSC,
    'obo': OBO,
    'vann': VANN,
    'prov': PROV,
    'p-plan': PPLAN,
    'dqv': DQV,
    'oa': OA,
    'void': VOID,
    'sd': SD,
    'formats': FORMATS,
    'dcterms': DCTERMS,
    'owl': OWL,
    'rdf': RDF,
    'rdfs': RDFS,
    'skos': SKOS,
    'xsd': XSD,
}


def bind_prefixes(graph):
    """Bind the Cocos prefixes so serialized graphs use them."""
    for prefix, namespace in PREFIXES.items():
        graph.bind(prefix, namespace, override=True, replace=True)
    return graph
