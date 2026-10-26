"""How much a prediction can be trusted, computed from the provenance of its sample and from what
the descriptor of its model says (provenance-based trust).

The evidence is read with SPARQL: from the registry graph, the organisms of the model, its quality
measurements (DQV), how its training data was annotated and the SHA-256 of its weights; from the
RDF of the sample with its provenance (PROV-O), its organism, the weights the prediction used and
the annotation its input comes from, followed back through the activities that generated it.

The rules, their thresholds, judgements and texts are in trust_rules.toml, so that they can be
changed without touching the code. The file is read each time, so a change applies at once.
"""
import tomllib

from django.conf import settings

from .discovery.graphs import is_a, label
from .namespaces import OBO, PREFIXES

F1 = OBO.STATO_0000628
SAMPLE_SIZE = OBO.NCIT_C53190
PROPORTION = OBO.STATO_0000607
IS_ABOUT = OBO.IAO_0000136

RULES_FILE = settings.BASE_DIR / 'trust_rules.toml'

JUDGEMENTS = ('for', 'caution', 'serious')  # from best to worst

# What each rule needs in the file: its numeric thresholds, the outcomes it can have besides 'for'
# (an outcome named 'caution' or 'serious' is that judgement; any other is set in the file), and
# the values its texts can use.
RULES = {
    'species': {'thresholds': (), 'outcomes': ('unknown', 'outside'), 'values': ('organism', 'range')},
    'antibiotic_isolates': {'thresholds': ('caution_below', 'serious_below'), 'outcomes': ('caution', 'serious'),
                            'values': ('antibiotic', 'isolates')},
    'class_balance': {'thresholds': ('caution_below', 'caution_above'), 'outcomes': ('few_resistant', 'few_susceptible'),
                      'values': ('antibiotic', 'percent')},
    'species_isolates': {'thresholds': ('caution_below',), 'outcomes': ('caution', 'absent'),
                         'values': ('antibiotic', 'organism', 'isolates')},
    'model_quality': {'thresholds': ('caution_below',), 'outcomes': ('caution',), 'values': ('f1',)},
    'same_annotation': {'thresholds': (), 'outcomes': ('different',), 'values': ('used', 'trained')},
    'weights': {'thresholds': (), 'outcomes': ('different',), 'values': ('antibiotic',)},
    'annotation_origin': {'thresholds': (), 'outcomes': ('unknown',), 'values': ()},
}


class RulesError(ValueError):
    """trust_rules.toml has a mistake."""


def load_rules(path=None):
    """The rules of trust_rules.toml (or of `path`), checked: {'levels': {...}, 'rules': {...}}."""
    path = path or RULES_FILE
    try:
        with open(path, 'rb') as file:
            config = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RulesError(f'{path} cannot be read: {error}')
    check_rules(config)
    return config


def check_rules(config):
    """Raise RulesError with every mistake of the rules `config`."""
    problems = []
    levels = config.get('levels', {})
    problems += [f'[levels] has no "{judgement}"' for judgement in JUDGEMENTS if judgement not in levels]
    rules = config.get('rules', {})
    problems += [f'[rules.{name}] is not a rule Cocos knows' for name in sorted(set(rules) - set(RULES))]
    for name, spec in RULES.items():
        rule = rules.get(name)
        if rule is None:
            problems.append(f'[rules.{name}] is missing')
            continue
        problems += _rule_problems(name, rule, spec)
    if problems:
        raise RulesError('; '.join(problems))


def _rule_problems(name, rule, spec):
    problems = []
    if not isinstance(rule.get('enabled'), bool):
        problems.append(f'[rules.{name}] enabled must be true or false')
    for threshold in spec['thresholds']:
        if isinstance(rule.get(threshold), bool) or not isinstance(rule.get(threshold), (int, float)):
            problems.append(f'[rules.{name}] {threshold} must be a number')
    for outcome in spec['outcomes']:
        if outcome not in JUDGEMENTS and rule.get(outcome) not in JUDGEMENTS:
            problems.append(f'[rules.{name}] {outcome} must be one of {", ".join(JUDGEMENTS)}')
    texts = rule.get('text', {})
    sample_values = {value: '…' for value in spec['values']}
    for outcome in ('for', *spec['outcomes']):
        if not isinstance(texts.get(outcome), str):
            problems.append(f'[rules.{name}.text] has no "{outcome}"')
            continue
        try:
            texts[outcome].format(**sample_values)
        except (KeyError, IndexError, ValueError) as error:
            problems.append(f'[rules.{name}.text] {outcome} uses an unknown value: {error}')
    return problems


def judgement(rule, outcome):
    """The judgement of an outcome of a rule: 'for', 'caution' or 'serious'."""
    return outcome if outcome in JUDGEMENTS else rule[outcome]


# --- Evidence

ANTIBIOTICS = 'SELECT ?antibiotic WHERE { ?model amrf:predictsResistanceTo ?antibiotic }'

RANGE = 'SELECT ?taxon WHERE { ?model schema:taxonomicRange ?taxon }'

MEASUREMENTS = """
SELECT ?measurement ?metric ?value WHERE {
    ?model dqv:hasQualityMeasurement ?measurement .
    ?measurement dqv:isMeasurementOf ?metric ; dqv:value ?value .
}"""

# How the training data of the model was annotated: the software and databases of the activity
# that generated it. The input of a prediction is followed back through the activities that
# generated it, up to the data the user uploaded, looking for the same software.
TRAINING_ANNOTATION = """
SELECT ?tool ?label ?databaseLabel WHERE {
    ?model prov:wasDerivedFrom/prov:wasGeneratedBy ?activity .
    ?activity prov:wasAssociatedWith ?agent .
    ?agent prov:specializationOf ?tool ; rdfs:label ?label .
    OPTIONAL { ?activity prov:used ?database . ?database schema:name ?name ; rdfs:label ?databaseLabel }
}"""

INPUT_ANNOTATION = """
SELECT ?tool ?label ?databaseLabel WHERE {
    ?prediction (prov:used/prov:wasGeneratedBy)+ ?activity .
    ?activity prov:wasAssociatedWith ?agent .
    ?agent prov:specializationOf ?tool ; rdfs:label ?label .
    OPTIONAL { ?activity prov:used ?database . ?database a prov:Entity ; schema:name ?name ; rdfs:label ?databaseLabel
               FILTER NOT EXISTS { ?database schema:sha256 ?sha256 } }
}"""

DECLARED_WEIGHTS = """
SELECT ?sha256 WHERE { ?model schema:hasPart ?file . ?file schema:sha256 ?sha256 ; obo:IAO_0000136 ?antibiotic }"""

USED_WEIGHTS = 'SELECT ?sha256 WHERE { ?prediction prov:used ?weights . ?weights a prov:Entity ; schema:sha256 ?sha256 }'

ORGANISM = 'SELECT ?taxon WHERE { ?sample schema:taxonomicRange ?taxon }'


def antibiotic_iri(registry, model, name):
    """The ARO term of the antibiotic `name` (e.g. 'amikacin') that `model` predicts, or None."""
    rows = registry.query(ANTIBIOTICS, initNs=PREFIXES, initBindings={'model': model})
    return next((row.antibiotic for row in rows if label(registry, row.antibiotic) == name), None)


def evidence(registry, sample_graph, sample, prediction, model, antibiotic):
    """What the graphs say about a prediction of `antibiotic` by `model`: `prediction` is its
    activity in `sample_graph`, the RDF of `sample` with its provenance. `antibiotic` is None if
    the model does not say which term it is: then nothing is known about its data for it."""
    def query(graph, text, **bindings):
        return list(graph.query(text, initNs=PREFIXES, initBindings=bindings))

    overall, by_taxa = {}, {}
    for row in query(registry, MEASUREMENTS, model=model):
        about = set(registry.objects(row.measurement, IS_ABOUT))
        if not about:
            overall[row.metric] = row.value.toPython()
        elif antibiotic in about:
            by_taxa.setdefault(frozenset(about - {antibiotic}), {})[row.metric] = row.value.toPython()
    trained = _annotation(query(registry, TRAINING_ANNOTATION, model=model))
    used = _annotation(query(sample_graph, INPUT_ANNOTATION, prediction=prediction))
    return {
        'organism': next((row.taxon for row in query(sample_graph, ORGANISM, sample=sample)), None),
        'range': [row.taxon for row in query(registry, RANGE, model=model)],
        'f1': overall.get(F1),
        'antibiotic': by_taxa.get(frozenset(), {}),               # {metric: value}
        'species': {taxa: values for taxa, values in by_taxa.items() if taxa},
        'trained': trained,
        'used': {tool: found for tool, found in used.items() if tool in trained},
        'declared_weights': set() if antibiotic is None else
                            {str(row.sha256) for row in query(registry, DECLARED_WEIGHTS, model=model, antibiotic=antibiotic)},
        'used_weights': {str(row.sha256) for row in query(sample_graph, USED_WEIGHTS, prediction=prediction)},
    }


def _annotation(rows):
    """{tool: 'Bakta 1.12.1 and Bakta database 6.0 (light)'} of the rows of an annotation query."""
    tools = {}
    for row in rows:
        databases = tools.setdefault(row.tool, (str(row.label), set()))[1]
        if row.databaseLabel is not None:
            databases.add(str(row.databaseLabel))
    return {tool: ' and '.join([name, *sorted(databases)]) for tool, (name, databases) in tools.items()}


# --- Rules

def assess(registry, facts, antibiotic_name, rules=None):
    """The trust of a prediction, from its `facts` (see evidence()) and the rules:
    {'judgement', 'level', 'evidence': [{'rule', 'judgement', 'text'}, ...]}, worst evidence first."""
    rules = rules or load_rules()
    organism = facts['organism']
    values = {'antibiotic': antibiotic_name, 'organism': label(registry, organism) if organism is not None else ''}
    found = []
    for name, check in CHECKS.items():
        rule = rules['rules'][name]
        result = check(registry, facts, rule) if rule['enabled'] else None
        if result is None:
            continue  # turned off, or the graphs do not say enough to check it
        outcome, extra = result
        found.append({'rule': name, 'judgement': judgement(rule, outcome),
                      'text': rule['text'][outcome].format(**values, **extra)})
    found.sort(key=lambda item: -JUDGEMENTS.index(item['judgement']))
    worst = found[0]['judgement'] if found else 'for'
    return {'judgement': worst, 'level': rules['levels'][worst], 'evidence': found}


def check_species(registry, facts, rule):
    if not facts['range']:
        return None
    names = {'range': ', '.join(sorted(label(registry, taxon) for taxon in facts['range']))}
    if facts['organism'] is None:
        return 'unknown', names
    if any(is_a(registry, facts['organism'], taxon) for taxon in facts['range']):
        return 'for', names
    return 'outside', names


def check_antibiotic_isolates(registry, facts, rule):
    isolates = facts['antibiotic'].get(SAMPLE_SIZE)
    if isolates is None:
        return None
    if isolates < rule['serious_below']:
        outcome = 'serious'
    else:
        outcome = 'caution' if isolates < rule['caution_below'] else 'for'
    return outcome, {'isolates': f'{int(isolates):,}'}


def check_class_balance(registry, facts, rule):
    proportion = facts['antibiotic'].get(PROPORTION)
    if proportion is None:
        return None
    percent = float(proportion) * 100
    if percent < rule['caution_below']:
        outcome = 'few_resistant'
    else:
        outcome = 'few_susceptible' if percent > rule['caution_above'] else 'for'
    return outcome, {'percent': f'{percent:.1f}'.removesuffix('.0')}


def check_species_isolates(registry, facts, rule):
    if facts['organism'] is None or not facts['species']:
        return None
    # The measurements about the organism of the sample or a taxon it belongs to (e.g. a strain of E. coli)
    counts = [values.get(SAMPLE_SIZE, 0) for taxa, values in facts['species'].items()
              if any(is_a(registry, facts['organism'], taxon) for taxon in taxa)]
    if not counts:
        return 'absent', {}
    isolates = max(counts)
    return ('caution' if isolates < rule['caution_below'] else 'for'), {'isolates': f'{int(isolates):,}'}


def check_model_quality(registry, facts, rule):
    if facts['f1'] is None:
        return None
    return ('caution' if facts['f1'] < rule['caution_below'] else 'for'), {'f1': str(facts['f1'])}


def check_same_annotation(registry, facts, rule):
    if not facts['used']:
        return None  # Cocos does not know how the input was annotated (see annotation_origin)
    tools = sorted(facts['used'])
    used = ', '.join(facts['used'][tool] for tool in tools)
    trained = ', '.join(facts['trained'][tool] for tool in tools)
    return ('for' if used == trained else 'different'), {'used': used, 'trained': trained}


def check_weights(registry, facts, rule):
    if not facts['declared_weights'] or not facts['used_weights']:
        return None
    return ('for' if facts['declared_weights'] & facts['used_weights'] else 'different'), {}


def check_annotation_origin(registry, facts, rule):
    if not facts['trained']:
        return None  # the model does not say how its data was annotated
    return ('for' if facts['used'] else 'unknown'), {}


CHECKS = {
    'species': check_species,
    'antibiotic_isolates': check_antibiotic_isolates,
    'class_balance': check_class_balance,
    'species_isolates': check_species_isolates,
    'model_quality': check_model_quality,
    'same_annotation': check_same_annotation,
    'weights': check_weights,
    'annotation_origin': check_annotation_origin,
}
