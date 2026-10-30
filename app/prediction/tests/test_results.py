"""The result of a model for one antibiotic: a call, a score or both, and its evidence."""
from django.test import SimpleTestCase

from prediction.models import NO_RESULT
from prediction.results import as_result, make_result, result_label


class ResultTests(SimpleTestCase):
    def test_a_number_is_a_score(self):
        self.assertEqual(as_result(0.25), {'score': 0.25})
        self.assertEqual(as_result(1), {'score': 1.0})

    def test_a_dict_keeps_its_call_score_and_evidence(self):
        self.assertEqual(as_result({'call': 'R', 'score': 0.9, 'evidence': [{'gene': 'blaKPC-2'}]}),
                         {'call': 'R', 'score': 0.9, 'evidence': [{'gene': 'blaKPC-2'}]})
        self.assertEqual(as_result({'call': 'not_detected', 'evidence': []}), {'call': 'not_detected'})

    def test_rejects_invalid_results(self):
        cases = [
            ('neither a call nor a score', {}),
            ('unknown call', {'call': 'resistant'}),
            ('score above 1', {'score': 1.5}),
            ('negative score', {'score': -0.1}),
            ('unknown key', {'call': 'R', 'probability': 0.9}),
        ]
        for label, value in cases:
            with self.subTest(label), self.assertRaises(ValueError):
                as_result(value)
        with self.assertRaises(ValueError):
            make_result(score=float('nan'))

    def test_label_is_the_rounded_score_or_else_the_call(self):
        self.assertEqual(result_label({'score': 0.123456, 'call': 'R'}), 0.1235)
        self.assertEqual(result_label({'call': 'S'}), 'Susceptible')
        self.assertEqual(result_label({'call': 'not_detected'}), 'Not detected')
        self.assertEqual(result_label(NO_RESULT), '')
        self.assertEqual(result_label(None), '')
