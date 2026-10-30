"""The result of a model for one antibiotic, the same for every kind of model.

A result is a dict with a `score` (the probability of resistance, from 0 to 1), a `call` (a verdict:
one of CALLS) or both, and optionally the `evidence` behind it (e.g. the genes a tool found). A
trained model usually gives a score; a rule-based tool, a call and its evidence. An antibiotic that
could not be predicted has NO_RESULT instead of a result.
"""
from .models import NO_RESULT

CALLS = {
    'R': 'Resistant',
    'S': 'Susceptible',
    'not_detected': 'Not detected',   # no known determinant found, which is not the same as susceptible
}


def make_result(call=None, score=None, evidence=None):
    """A result with a call, a score or both. Raise ValueError if it has neither or one is invalid."""
    if call is None and score is None:
        raise ValueError('A result needs a call or a score.')
    result = {}
    if call is not None:
        if call not in CALLS:
            raise ValueError(f'Unknown call {call!r}; expected one of {", ".join(CALLS)}.')
        result['call'] = call
    if score is not None:
        score = float(score)
        if not 0 <= score <= 1:
            raise ValueError(f'The score must be between 0 and 1, not {score}.')
        result['score'] = score
    if evidence:
        result['evidence'] = list(evidence)
    return result


def as_result(value):
    """The result of what a model returned: a number is its score; a dict, its call, score and evidence."""
    if isinstance(value, dict):
        unknown = set(value) - {'call', 'score', 'evidence'}
        if unknown:
            raise ValueError(f'Unknown keys in a result: {", ".join(sorted(unknown))}.')
        return make_result(**value)
    return make_result(score=value)


def result_label(result):
    """How a result reads in a CSV: its score, rounded, or else its call ('' for NO_RESULT)."""
    if result in (None, NO_RESULT):
        return ''
    if result.get('score') is not None:
        return round(result['score'], 4)
    return CALLS[result['call']]
