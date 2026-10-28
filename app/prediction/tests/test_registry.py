from contextlib import contextmanager
from unittest.mock import patch

from django.test import TestCase

from core.models import File
from core.steps import DataKind, Port
from prediction.adapters.registry import (
    ANY_ORGANISM,
    MODEL_ANTIBIOTICS,
    MODEL_ORGANISMS,
    MODEL_PORTS,
    MODEL_REGISTRY,
    get_model_adapter_class,
    get_model_ports,
    get_model_supported_antibiotics,
    get_model_supported_organisms,
    list_all_organisms,
    list_registered_models,
    register_model,
)
from semantics.registry.plugins import REJECTED_PLUGINS, ModelDescription

GENES = (Port('genes', DataKind.GENE_SET, File.FileType.JSON),)
PREDICTIONS = (Port('predictions', DataKind.RESISTANCE_PREDICTION, File.FileType.CSV),)


def description(organisms=None, antibiotics=('amikacin',)):
    """What a descriptor declares: any organism unless `organisms` ({CURIE: name}) is given."""
    return ModelDescription(inputs=GENES, outputs=PREDICTIONS, any_organism=organisms is None,
                            organisms=dict(organisms or {}), antibiotics=tuple(antibiotics))


@contextmanager
def describing(**kwargs):
    """Patch the descriptor reader so registered test models declare `kwargs`."""
    with patch('prediction.adapters.registry.describe_model', return_value=description(**kwargs)):
        yield


class RegistryTests(TestCase):
    def setUp(self):
        self._registry_backup = dict(MODEL_REGISTRY)
        MODEL_REGISTRY.clear()
        self.enterContext(describing())

    def tearDown(self):
        MODEL_REGISTRY.clear()
        MODEL_REGISTRY.update(self._registry_backup)

    def test_register_and_lookup_model_case_insensitive(self):
        @register_model("test_model")
        class DummyAdapter:
            def __init__(self, antibiotic: str):
                self.antibiotic = antibiotic

        self.assertIs(get_model_adapter_class("test_model"), DummyAdapter)
        self.assertIs(get_model_adapter_class("TEST_MODEL"), DummyAdapter)
        self.assertIn("test_model", list_registered_models())

    def test_register_uses_class_name_when_alias_missing(self):
        @register_model()
        class NamedAdapter:
            def __init__(self, antibiotic: str):
                self.antibiotic = antibiotic

        self.assertIs(get_model_adapter_class("namedadapter"), NamedAdapter)

    def test_get_model_adapter_class_returns_none_for_missing_name(self):
        self.assertIsNone(get_model_adapter_class(None))
        self.assertIsNone(get_model_adapter_class("unknown"))

    def test_register_model_requires_antibiotic_parameter(self):
        with self.assertRaises(TypeError):
            @register_model("invalid_adapter")
            class InvalidAdapter:
                def __init__(self):
                    pass

    @patch("prediction.adapters.registry.inspect.signature", side_effect=TypeError("boom"))
    def test_register_model_raises_when_signature_cannot_be_inspected(self, _mock_signature):
        with self.assertRaisesRegex(TypeError, "Cannot inspect __init__ of adapter"):
            @register_model("broken_adapter")
            class BrokenAdapter:
                def __init__(self, antibiotic: str):
                    self.antibiotic = antibiotic



class ModelDescriptorTests(TestCase):
    """What a model supports comes from its descriptor."""

    def setUp(self):
        registries = (MODEL_REGISTRY, MODEL_ANTIBIOTICS, MODEL_ORGANISMS, MODEL_PORTS, REJECTED_PLUGINS)
        backups = [dict(registry) for registry in registries]

        def restore():
            for registry, backup in zip(registries, backups):
                registry.clear()
                registry.update(backup)
        self.addCleanup(restore)

    def register(self, name, **kwargs):
        with describing(**kwargs):
            @register_model(name)
            class Adapter:
                def __init__(self, antibiotic: str):
                    pass

    def test_organisms_antibiotics_and_ports_come_from_the_descriptor(self):
        self.register('test_ecoli', organisms={'NCBITaxon:562': 'Escherichia coli'}, antibiotics=('amikacin', 'meropenem'))
        self.register('test_tb', organisms={'NCBITaxon:1773': 'Mycobacterium tuberculosis', 'NCBITaxon:562': 'Escherichia coli'})
        self.register('test_any')

        self.assertEqual(get_model_supported_organisms('TEST_ECOLI'), {'NCBITaxon:562': 'Escherichia coli'})
        self.assertEqual(get_model_supported_antibiotics('test_ecoli'), ['amikacin', 'meropenem'])
        self.assertEqual(get_model_ports('test_ecoli'), (GENES, PREDICTIONS))
        self.assertIs(get_model_supported_organisms('test_any'), ANY_ORGANISM)
        organisms = list_all_organisms()
        self.assertIn(('NCBITaxon:1773', 'Mycobacterium tuberculosis'), organisms)
        names = [name for _, name in organisms]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), len(set(names)))

    def test_a_model_without_descriptor_is_skipped_and_reported(self):
        @register_model("test_without_descriptor")
        class Adapter:
            def __init__(self, antibiotic: str):
                pass

        self.assertNotIn('test_without_descriptor', list_registered_models())
        self.assertIn('not found', REJECTED_PLUGINS[('model', 'test_without_descriptor')])

    def test_a_model_without_weights_is_registered(self):
        self.register('test_rule_based', antibiotics=('amikacin', 'meropenem'))

        self.assertIn('test_rule_based', list_registered_models())
        self.assertNotIn(('model', 'test_rule_based'), REJECTED_PLUGINS)

    def test_real_models_support_any_organism(self):
        for name in ('base_bakta_50', 'base_bakta_90'):
            with self.subTest(name):
                self.assertIs(get_model_supported_organisms(name), ANY_ORGANISM)
