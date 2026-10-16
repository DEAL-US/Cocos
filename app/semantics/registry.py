"""The registry graph: every step and model COCOS offers, described in RDF.

It joins the AMRF vocabulary, the steps of the framework (generated from the code), the
descriptors of the parsers and models (written by hand) and the labels and hierarchy of the
reused ontology terms (terms.ttl). Every access to the graph goes through this module, so it
could be served from a triplestore without changing its users.
"""
from functools import lru_cache

from rdflib import Graph

from conversion.parsers import PARSERS
from core.steps import list_steps
from prediction.adapters.registry import list_registered_models

from .descriptors import load_descriptor, model_descriptor_path, model_iri, parser_descriptor_path
from .namespaces import bind_prefixes
from .steps_graph import step_iri, steps_graph
from .terms import TERMS_FILE
from .vocabulary import load_vocabulary

# Gene extraction steps are described by the descriptor of their parser, and prediction steps
# by the descriptor of their model.
DESCRIBED_BY_DESCRIPTORS = ('extraction', 'prediction')


def framework_steps():
    """The steps described from the code."""
    return [step for step in list_steps() if step.category not in DESCRIBED_BY_DESCRIPTORS]


def step_resource(step):
    """IRI of the resource that describes a step: a prediction step is described as its model."""
    if step.category == 'prediction':
        return model_iri(step.model_name)
    return step_iri(step)


def build_registry_graph(include_terms=True):
    graph = bind_prefixes(Graph())
    graph += load_vocabulary()
    graph += steps_graph(framework_steps())
    for name in PARSERS:
        graph += load_descriptor(parser_descriptor_path(name))
    for name in list_registered_models():
        graph += load_descriptor(model_descriptor_path(name))
    if include_terms and TERMS_FILE.exists():
        graph.parse(TERMS_FILE, format='turtle')
    return graph


@lru_cache(maxsize=1)
def registry_graph():
    """The registry graph, built once per process. Treat it as read-only."""
    return build_registry_graph()
