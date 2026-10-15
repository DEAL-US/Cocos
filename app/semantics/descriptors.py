"""Hand-written descriptors of the plug-ins: one descriptor.ttl in each model and parser folder."""
from pathlib import Path

from django.conf import settings
from rdflib import Graph

from .namespaces import COCOS, bind_prefixes

DESCRIPTOR_FILENAME = 'descriptor.ttl'


def model_iri(model_name):
    return COCOS[f'model/{model_name}']


def model_descriptor_path(model_name):
    return Path(settings.BASE_DIR) / 'ai_models' / model_name / DESCRIPTOR_FILENAME


def parser_descriptor_path(parser_name):
    return Path(settings.BASE_DIR) / 'parsers' / parser_name / DESCRIPTOR_FILENAME


def load_descriptor(path):
    """Return the graph of one descriptor. Raise FileNotFoundError if it does not exist."""
    graph = bind_prefixes(Graph())
    graph.parse(path, format='turtle')
    return graph
