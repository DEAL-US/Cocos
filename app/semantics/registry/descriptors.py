"""Hand-written descriptors of the plug-ins: one descriptor.ttl in each model and parser folder.

Next to it, a plug-in can have a quality.ttl with measurements of how well it works (DQV: e.g. its
F1 score, or how many isolates it was trained or validated on), read as part of its descriptor.
"""
from pathlib import Path

from django.conf import settings
from rdflib import Graph

from ..namespaces import COCOS, bind_prefixes

DESCRIPTOR_FILENAME = 'descriptor.ttl'
QUALITY_FILENAME = 'quality.ttl'


def model_iri(model_name):
    return COCOS[f'model/{model_name}']


def model_descriptor_path(model_name):
    return Path(settings.BASE_DIR) / 'ai_models' / model_name / DESCRIPTOR_FILENAME


def parser_descriptor_path(parser_name):
    return Path(settings.BASE_DIR) / 'parsers' / parser_name / DESCRIPTOR_FILENAME


def all_descriptor_paths():
    """Every descriptor on disk, including those of plug-ins that could not be registered."""
    base_dir = Path(settings.BASE_DIR)
    return sorted([*base_dir.glob(f'ai_models/*/{DESCRIPTOR_FILENAME}'), *base_dir.glob(f'parsers/*/{DESCRIPTOR_FILENAME}')])


def load_descriptor(path):
    """Return the graph of one descriptor, with the quality.ttl next to it, if there is one."""
    graph = bind_prefixes(Graph())
    graph.parse(path, format='turtle')
    quality = Path(path).with_name(QUALITY_FILENAME)
    if quality.exists():
        graph.parse(quality, format='turtle')
    return graph
