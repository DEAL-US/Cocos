"""What discovery reads from the graphs, with SPARQL, turned into plain Python objects.

From the registry graph: the steps and models (read_tools). From the sample graph: the data it
has and its organism (read_sample). And, through Terms, whether a term is a kind of another and
how it is called.
"""
from dataclasses import dataclass, field

from rdflib import URIRef

from ..namespaces import AMRF, BSC, EDAM, RDFS, SCHEMA
from ..registry.steps import WEB_SERVICE
from .results import Source

NAMESPACES = {'schema': SCHEMA, 'bsc': BSC, 'edam': EDAM, 'amrf': AMRF, 'rdfs': RDFS}


@dataclass(frozen=True)
class Kind:
    """What a piece of data is: EDAM data and format, and the sequencing technique of reads."""
    data: URIRef
    format: URIRef
    technique: URIRef | None = None


@dataclass(frozen=True)
class Parameter:
    """An input or output of a step or model."""
    role: str
    kind: Kind


@dataclass(frozen=True)
class Tool:
    """A step or a model, as the registry describes it. Models also have organisms and antibiotics."""
    identifier: str
    inputs: tuple
    outputs: tuple
    is_model: bool = False
    web_service: bool = False                      # runs as a job in the bio service
    organisms: dict = field(default_factory=dict)  # {NCBITaxon IRI: name}
    antibiotics: frozenset = frozenset()           # names, e.g. {'amikacin'}


@dataclass(frozen=True)
class Item:
    """A piece of data the sample has, or would have after some steps."""
    kind: Kind
    source: Source


# --- Registry

TOOLS_QUERY = """
SELECT ?tool ?identifier ?operation ?category WHERE {
    ?tool a schema:SoftwareApplication ; schema:identifier ?identifier ; schema:featureList ?operation .
    OPTIONAL { ?tool schema:applicationCategory ?category }
}
"""

PARAMETERS_QUERY = """
SELECT ?tool ?direction ?role ?data ?format ?technique WHERE {
    { ?tool bsc:input ?parameter . BIND("input" AS ?direction) }
    UNION
    { ?tool bsc:output ?parameter . BIND("output" AS ?direction) }
    ?parameter schema:name ?role ; schema:additionalType ?data ; schema:encodingFormat ?format .
    OPTIONAL { ?parameter schema:measurementTechnique ?technique }
}
"""

MODEL_SCOPE_QUERY = """
SELECT ?model ?organism ?organismName ?antibioticName WHERE {
    ?model schema:featureList edam:operation_3482 .
    { ?model schema:taxonomicRange ?organism . OPTIONAL { ?organism rdfs:label ?organismName } }
    UNION
    { ?model amrf:predictsResistanceTo ?antibiotic . ?antibiotic rdfs:label ?antibioticName }
}
"""


def read_tools(registry):
    """Every step and model of the registry graph, sorted by identifier."""
    parameters = {}
    for row in registry.query(PARAMETERS_QUERY, initNs=NAMESPACES):
        parameter = Parameter(str(row.role), Kind(row.data, row.format, row.technique))
        parameters.setdefault((row.tool, str(row.direction)), []).append(parameter)

    organisms, antibiotics = {}, {}
    for row in registry.query(MODEL_SCOPE_QUERY, initNs=NAMESPACES):
        if row.organism is not None:
            organisms.setdefault(row.model, {})[row.organism] = str(row.organismName or _short(row.organism))
        if row.antibioticName is not None:
            antibiotics.setdefault(row.model, set()).add(str(row.antibioticName))

    tools = {}
    for row in registry.query(TOOLS_QUERY, initNs=NAMESPACES):
        tool = tools.setdefault(row.tool, {'identifier': str(row.identifier), 'model': False, 'web': False})
        tool['model'] |= row.operation == EDAM.operation_3482
        tool['web'] |= row.category is not None and str(row.category) == WEB_SERVICE

    return sorted((
        Tool(
            identifier=tool['identifier'],
            inputs=_sorted_by_role(parameters.get((iri, 'input'), [])),
            outputs=_sorted_by_role(parameters.get((iri, 'output'), [])),
            is_model=tool['model'],
            web_service=tool['web'],
            organisms=organisms.get(iri, {}),
            antibiotics=frozenset(antibiotics.get(iri, ())),
        )
        for iri, tool in tools.items()
    ), key=lambda tool: tool.identifier)


# --- Sample

SAMPLE_QUERY = """
SELECT ?file ?role ?data ?format ?technique WHERE {
    ?sample a schema:Dataset ; schema:hasPart ?entry .
    ?entry schema:identifier ?file ; schema:name ?role ;
           schema:additionalType ?data ; schema:encodingFormat ?format .
    OPTIONAL { ?entry schema:measurementTechnique ?technique }
}
"""

SAMPLE_ORGANISM_QUERY = 'SELECT ?organism WHERE { ?sample a schema:Dataset ; schema:taxonomicRange ?organism . }'


def read_sample(sample):
    """(items, organism): the data the sample has, and its organism (None if unknown)."""
    rows = sorted(sample.query(SAMPLE_QUERY, initNs=NAMESPACES), key=lambda row: (str(row.file), str(row.role)))
    items = tuple(Item(Kind(row.data, row.format, row.technique), Source(str(row.role), file=str(row.file)))
                  for row in rows)
    organisms = [row.organism for row in sample.query(SAMPLE_ORGANISM_QUERY, initNs=NAMESPACES)]
    return items, (organisms[0] if organisms else None)


# --- Terms

SUBCLASS_QUERY = 'ASK { ?narrower rdfs:subClassOf* ?broader }'
LABEL_QUERY = 'SELECT ?label WHERE { ?term rdfs:label ?label } LIMIT 1'


class Terms:
    """Questions about the terms, answered by the registry graph (it includes terms.ttl)."""

    def __init__(self, registry):
        self.registry = registry
        self._is_a = {}

    def is_a(self, narrower, broader):
        """Whether `narrower` is `broader` or a kind of it (e.g. Bakta JSON is a JSON)."""
        if narrower == broader:
            return True
        if (narrower, broader) not in self._is_a:
            answer = self.registry.query(SUBCLASS_QUERY, initNs=NAMESPACES,
                                         initBindings={'narrower': narrower, 'broader': broader})
            self._is_a[(narrower, broader)] = bool(answer.askAnswer)
        return self._is_a[(narrower, broader)]

    def label(self, term):
        rows = list(self.registry.query(LABEL_QUERY, initNs=NAMESPACES, initBindings={'term': term}))
        return str(rows[0].label) if rows else _short(term)


def _sorted_by_role(parameters):
    return tuple(sorted(parameters, key=lambda parameter: parameter.role))


def _short(term):
    return str(term).rsplit('/', 1)[-1]
