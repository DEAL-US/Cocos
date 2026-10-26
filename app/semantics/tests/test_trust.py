import copy
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from semantics.checks import check_trust_rules
from semantics.trust import RULES, RulesError, check_rules, load_rules


class TrustRulesFileTests(SimpleTestCase):
    """trust_rules.toml holds every rule, and its mistakes are reported."""

    def setUp(self):
        self.config = load_rules()

    def broken(self, change):
        config = copy.deepcopy(self.config)
        change(config)
        with self.assertRaises(RulesError) as raised:
            check_rules(config)
        return str(raised.exception)

    def test_the_file_of_cocos_has_every_rule_and_level(self):
        self.assertEqual(set(self.config['rules']), set(RULES))
        self.assertEqual(self.config['levels']['serious'], 'Low')
        self.assertEqual(check_trust_rules(None), [])

    def test_mistakes_are_reported(self):
        cases = {
            'unknown rule': (lambda c: c['rules'].update(nonsense={}), 'nonsense'),
            'missing rule': (lambda c: c['rules'].pop('weights'), 'weights] is missing'),
            'threshold as text': (lambda c: c['rules']['antibiotic_isolates'].update(caution_below='500'),
                                  'caution_below must be a number'),
            'unknown judgement': (lambda c: c['rules']['species'].update(unknown='maybe'), 'unknown must be one of'),
            'missing text': (lambda c: c['rules']['model_quality']['text'].pop('caution'), 'has no "caution"'),
            'unknown value': (lambda c: c['rules']['model_quality']['text'].update(caution='{auc}'), 'unknown value'),
            'missing level': (lambda c: c['levels'].pop('caution'), '[levels] has no "caution"'),
        }
        for label, (change, message) in cases.items():
            with self.subTest(label):
                self.assertIn(message, self.broken(change))

    def test_a_file_that_cannot_be_read_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rules.toml'
            path.write_text('[levels\n', encoding='utf-8')
            with self.assertRaisesMessage(RulesError, 'cannot be read'):
                load_rules(path)
