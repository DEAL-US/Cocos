"""SHACL validation of descriptions against the AMRF shapes (vocab/shapes.ttl)."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import BNode, Graph
from rdflib.namespace import RDF, SH

from .namespaces import bind_prefixes
from .registry.terms import terms_graph
from .registry.vocabulary import load_vocabulary

SHAPES_FILE = Path(__file__).resolve().parent / 'vocab' / 'shapes.ttl'


@dataclass(frozen=True, order=True)
class Problem:
    """One result of a validation: the node, the property and what is wrong with them."""
    focus: str
    path: str
    message: str
    severity: str  # 'Violation', 'Warning' or 'Info'

    def __str__(self):
        where = f'{self.focus} ({self.path})' if self.path else self.focus
        return f'{where}: {self.message}'


@lru_cache(maxsize=1)
def shapes_graph():
    return Graph().parse(SHAPES_FILE, format='turtle')


def validate(data_graph):
    """Validate `data_graph` and return its problems, sorted.

    The AMRF vocabulary and terms.ttl are added to the data, since the shapes follow the
    hierarchy of the reused terms (e.g. that meropenem is an antibiotic molecule).
    """
    graph = bind_prefixes(Graph())
    graph += data_graph
    graph += load_vocabulary()
    graph += terms_graph()
    _, report, _ = shacl_validate(graph, shacl_graph=shapes_graph(), advanced=True, allow_warnings=True)
    return sorted(_problems(report))


def violations(problems):
    return [problem for problem in problems if problem.severity == 'Violation']


def _problems(report):
    for result in report.subjects(RDF.type, SH.ValidationResult):
        path = report.value(result, SH.resultPath)
        yield Problem(
            focus=str(report.value(result, SH.focusNode)),
            path='' if path is None or isinstance(path, BNode) else report.namespace_manager.normalizeUri(path),
            message=str(report.value(result, SH.resultMessage) or ''),
            severity=str(report.value(result, SH.resultSeverity)).removeprefix(str(SH)),
        )
