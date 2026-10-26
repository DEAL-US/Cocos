"""How much a prediction can be trusted, computed from the provenance of its sample and from what
the descriptor of its model says (provenance-based trust).

The rules, their thresholds, judgements and texts are in trust_rules.toml, so that they can be
changed without touching the code. The file is read each time, so a change applies at once.
"""
import tomllib

from django.conf import settings

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
