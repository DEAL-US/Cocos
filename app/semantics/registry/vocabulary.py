"""The AMRF vocabulary: the few terms COCOS defines because no reused ontology has them."""
from pathlib import Path

from rdflib import Graph

from ..namespaces import bind_prefixes

VOCABULARY_FILE = Path(__file__).resolve().parents[1] / 'vocab' / 'amrf.ttl'


def load_vocabulary():
    """Return the AMRF vocabulary as a graph."""
    graph = bind_prefixes(Graph())
    graph.parse(VOCABULARY_FILE, format='turtle')
    return graph
