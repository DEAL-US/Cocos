"""Discovery: which models can run on a sample, decided only from RDF.

For each model of the registry graph, what it consumes is compared with what the sample graph has:

- ready: the sample already has every input of the model;
- reachable: a sequence of steps of the registry produces the missing inputs from what the sample
  has (the shortest one, found by breadth-first search over the data the sample would have);
- incompatible: no sequence of steps gets there, the model is not for the organism of the sample,
  or it predicts none of the requested antibiotics. The reasons are given.

Everything is read from the graphs with SPARQL: what each step and model consumes and produces
(EDAM data and format, and the sequencing technique of reads), the organisms and antibiotics of
the models, and whether a term is a kind of another (rdfs:subClassOf*, with the hierarchy of
terms.ttl and the AMRF vocabulary: a Bakta JSON file is a JSON file).

Among the shortest sequences, the one chosen recomputes the least data the sample already has,
then runs the fewest jobs in the bio service, then comes first by step identifiers.
"""
from dataclasses import dataclass
from enum import StrEnum

from rdflib import URIRef

from .namespaces import AMRF, BSC, EDAM, OBO, RDFS, SCHEMA
from .steps_graph import WEB_SERVICE

# A model for Bacteria accepts a sample of any organism (v1: no other taxonomy reasoning).
ANY_BACTERIA = OBO.NCBITaxon_2
PREDICTION = EDAM.operation_3482
MAX_STEPS = 6

NAMESPACES = {'schema': SCHEMA, 'bsc': BSC, 'edam': EDAM, 'amrf': AMRF, 'rdfs': RDFS}

PARAMETERS_QUERY = """
SELECT ?tool ?direction ?role ?data ?format ?technique WHERE {
    ?tool a schema:SoftwareApplication .
    { ?tool bsc:input ?parameter . BIND("input" AS ?direction) }
    UNION
    { ?tool bsc:output ?parameter . BIND("output" AS ?direction) }
    ?parameter schema:name ?role ; schema:additionalType ?data ; schema:encodingFormat ?format .
    OPTIONAL { ?parameter schema:measurementTechnique ?technique }
}
"""

TOOLS_QUERY = """
SELECT ?tool ?identifier ?category ?operation WHERE {
    ?tool a schema:SoftwareApplication ; schema:identifier ?identifier ; schema:featureList ?operation .
    OPTIONAL { ?tool schema:applicationCategory ?category }
}
"""

MODEL_TERMS_QUERY = """
SELECT ?model ?predicate ?term ?label WHERE {
    ?model schema:featureList edam:operation_3482 .
    VALUES ?predicate { schema:taxonomicRange amrf:predictsResistanceTo }
    ?model ?predicate ?term .
    OPTIONAL { ?term rdfs:label ?label }
}
"""

SAMPLE_QUERY = """
SELECT ?entry ?file ?role ?data ?format ?technique WHERE {
    ?sample a schema:Dataset ; schema:hasPart ?entry .
    ?entry schema:identifier ?file ; schema:name ?role ;
           schema:additionalType ?data ; schema:encodingFormat ?format .
    OPTIONAL { ?entry schema:measurementTechnique ?technique }
}
"""

SAMPLE_TAXON_QUERY = 'SELECT ?taxon WHERE { ?sample a schema:Dataset ; schema:taxonomicRange ?taxon . }'

SUBCLASS_QUERY = 'ASK { ?narrower rdfs:subClassOf* ?broader }'

LABEL_QUERY = 'SELECT ?label WHERE { ?term rdfs:label ?label } LIMIT 1'


class Status(StrEnum):
    READY = 'ready'
    REACHABLE = 'reachable'
    INCOMPATIBLE = 'incompatible'


@dataclass(frozen=True)
class Kind:
    """What a piece of data is: EDAM data and format, and the sequencing technique of reads."""
    data: URIRef
    format: URIRef
    technique: URIRef | None = None


@dataclass(frozen=True)
class Parameter:
    role: str
    kind: Kind


@dataclass(frozen=True)
class Tool:
    """A step or a model, as the registry graph describes it."""
    iri: URIRef
    identifier: str
    inputs: tuple
    outputs: tuple
    web_service: bool
    is_model: bool


@dataclass(frozen=True)
class Source:
    """Where an input comes from: a file of the sample (`file`), or an output of an earlier step of
    the path (`step`, its position in it); `role` is the role of that file or output."""
    role: str
    file: str | None = None
    step: int | None = None


@dataclass(frozen=True)
class PlannedStep:
    step: str
    inputs: tuple  # ((role, Source), ...)


@dataclass(frozen=True)
class Compatibility:
    model: str
    status: Status
    steps: tuple = ()       # PlannedStep, in order, when reachable
    inputs: tuple = ()      # ((role, Source), ...) of the model, when ready or reachable
    reasons: tuple = ()     # why it is incompatible


@dataclass(frozen=True)
class _Item:
    kind: Kind
    source: Source


def discover(registry, sample, antibiotics=None):
    """Return the Compatibility of every model of `registry` (a graph) with `sample` (a graph).

    `antibiotics`, if given, are the names of the antibiotics the user wants: a model that
    predicts none of them is incompatible.
    """
    return _Discovery(registry, sample).run(antibiotics)


class _Discovery:
    def __init__(self, registry, sample):
        self.registry = registry
        self.sample = sample
        self._subclass = {}
        self.tools = _read_tools(registry)
        self.steps = sorted((tool for tool in self.tools if not tool.is_model), key=lambda tool: tool.identifier)
        self.models = sorted((tool for tool in self.tools if tool.is_model), key=lambda tool: tool.identifier)
        self.model_terms = _read_model_terms(registry)
        self.items = _read_sample(sample)
        taxa = [row.taxon for row in sample.query(SAMPLE_TAXON_QUERY, initNs=NAMESPACES)]
        self.taxon = taxa[0] if taxa else None

    def run(self, antibiotics):
        return [self.check(model, antibiotics) for model in self.models]

    def check(self, model, antibiotics):
        reasons = [*self.organism_reasons(model), *self.antibiotic_reasons(model, antibiotics)]
        inputs = self.assign(model.inputs, self.items)
        if inputs is not None:
            return self.result(model, reasons, Status.READY, inputs=inputs)
        path = self.search(model)
        if path is None:
            reasons.append(self.data_reason(model))
            return Compatibility(model.identifier, Status.INCOMPATIBLE, reasons=tuple(reasons))
        steps, inputs = path
        return self.result(model, reasons, Status.REACHABLE, steps=steps, inputs=inputs)

    def result(self, model, reasons, status, steps=(), inputs=None):
        if reasons:
            return Compatibility(model.identifier, Status.INCOMPATIBLE, reasons=tuple(reasons))
        return Compatibility(model.identifier, status, steps=tuple(steps), inputs=_pairs(inputs))

    # --- Organism and antibiotics

    def organism_reasons(self, model):
        taxa = self.model_terms.get((model.iri, SCHEMA.taxonomicRange), {})
        if ANY_BACTERIA in taxa:
            return []
        names = ', '.join(sorted(taxa.values()))
        if self.taxon is None:
            return [f'This model is only for {names}, and the organism of this sample is unknown.']
        if self.taxon not in taxa:
            return [f'This model is only for {names}, and this sample is {self.label(self.taxon)}.']
        return []

    def antibiotic_reasons(self, model, antibiotics):
        if not antibiotics:
            return []
        predicted = set(self.model_terms.get((model.iri, AMRF.predictsResistanceTo), {}).values())
        if predicted & set(antibiotics):
            return []
        return ['This model predicts none of the selected antibiotics.']

    def data_reason(self, model):
        needed = ', '.join(f'{self.label(p.kind.data)} ({self.label(p.kind.format)})' for p in model.inputs)
        return f'This model needs {needed}, and no steps can obtain it from the data of this sample.'

    # --- Search

    def search(self, model):
        """Breadth-first search of the shortest sequence of steps after which `model` has its inputs.

        Returns (planned steps, model inputs) or None. Paths are expanded level by level; a step is
        only added if it produces a kind of data the path does not have yet.
        """
        level = [((), self.items, 0, 0)]  # (planned steps, items, recomputed outputs, web service jobs)
        seen = {self.signature(self.items)}
        for _ in range(MAX_STEPS):
            next_level, found = [], []
            for planned, items, recomputed, jobs in level:
                kinds = {item.kind for item in items}
                for step in self.steps:
                    inputs = self.assign(step.inputs, items)
                    if inputs is None or not any(output.kind not in kinds for output in step.outputs):
                        continue
                    index = len(planned)
                    produced = [_Item(output.kind, Source(output.role, step=index)) for output in step.outputs]
                    path = (
                        (*planned, PlannedStep(step.identifier, _pairs(inputs))),
                        (*items, *produced),
                        recomputed + sum(output.kind in kinds for output in step.outputs),
                        jobs + step.web_service,
                    )
                    model_inputs = self.assign(model.inputs, path[1])
                    if model_inputs is not None:
                        found.append((path, model_inputs))
                    elif self.signature(path[1]) not in seen:
                        next_level.append(path)
            if found:
                (planned, _, _, _), model_inputs = min(found, key=lambda entry: _cost(entry[0]))
                return planned, model_inputs
            seen |= {self.signature(items) for _, items, _, _ in next_level}
            level = next_level
        return None

    @staticmethod
    def signature(items):
        return frozenset(item.kind for item in items)

    # --- Matching

    def assign(self, parameters, items):
        """Give each parameter a distinct item that satisfies it, or return None.

        Items with the same role, then items produced by the path (the latest first), are preferred.
        """
        used, assigned = set(), []
        for parameter in parameters:
            candidates = [index for index, item in enumerate(items)
                          if index not in used and self.satisfies(item.kind, parameter.kind)]
            if not candidates:
                return None
            best = max(candidates, key=lambda index: (items[index].source.role == parameter.role,
                                                      items[index].source.step is not None, index))
            used.add(best)
            assigned.append((parameter.role, items[best].source))
        return assigned

    def satisfies(self, offered, required):
        if required.technique is not None and offered.technique != required.technique:
            return False
        return self.is_a(offered.data, required.data) and self.is_a(offered.format, required.format)

    def is_a(self, narrower, broader):
        if narrower == broader:
            return True
        key = (narrower, broader)
        if key not in self._subclass:
            result = self.registry.query(SUBCLASS_QUERY, initNs=NAMESPACES,
                                         initBindings={'narrower': narrower, 'broader': broader})
            self._subclass[key] = bool(result.askAnswer)
        return self._subclass[key]

    def label(self, term):
        rows = list(self.registry.query(LABEL_QUERY, initNs=NAMESPACES, initBindings={'term': term}))
        return str(rows[0].label) if rows else str(term).rsplit('/', 1)[-1]


def _cost(path):
    planned, _, recomputed, jobs = path
    return (len(planned), recomputed, jobs, tuple(step.step for step in planned))


def _pairs(assigned):
    return tuple(assigned or ())


def _read_tools(registry):
    parameters = {}
    for row in registry.query(PARAMETERS_QUERY, initNs=NAMESPACES):
        parameter = Parameter(str(row.role), Kind(row.data, row.format, row.technique))
        parameters.setdefault((row.tool, str(row.direction)), []).append(parameter)
    found = {}
    for row in registry.query(TOOLS_QUERY, initNs=NAMESPACES):
        tool = found.setdefault(row.tool, {'identifier': str(row.identifier), 'web': False, 'model': False})
        tool['web'] |= row.category is not None and str(row.category) == WEB_SERVICE
        tool['model'] |= row.operation == PREDICTION
    return [
        Tool(
            iri=iri,
            identifier=tool['identifier'],
            inputs=tuple(sorted(parameters.get((iri, 'input'), []), key=lambda p: p.role)),
            outputs=tuple(sorted(parameters.get((iri, 'output'), []), key=lambda p: p.role)),
            web_service=tool['web'],
            is_model=tool['model'],
        )
        for iri, tool in found.items()
    ]


def _read_model_terms(registry):
    """{(model, predicate): {term: label}} for the organisms and antibiotics of the models."""
    terms = {}
    for row in registry.query(MODEL_TERMS_QUERY, initNs=NAMESPACES):
        label = str(row.label) if row.label is not None else str(row.term).rsplit('/', 1)[-1]
        terms.setdefault((row.model, row.predicate), {})[row.term] = label
    return terms


def _read_sample(sample):
    return tuple(
        _Item(Kind(row.data, row.format, row.technique), Source(str(row.role), file=str(row.file)))
        for row in sorted(sample.query(SAMPLE_QUERY, initNs=NAMESPACES), key=lambda row: (str(row.file), str(row.role)))
    )
