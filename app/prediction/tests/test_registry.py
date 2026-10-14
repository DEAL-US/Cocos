from unittest.mock import patch

from django.test import TestCase

from prediction.adapters.registry import (
    ANY_ORGANISM,
    MODEL_ORGANISMS,
    MODEL_REGISTRY,
    get_model_adapter_class,
    get_model_supported_organisms,
    list_all_organisms,
    list_registered_models,
    register_model,
)


class RegistryTests(TestCase):
    def setUp(self):
        self._registry_backup = dict(MODEL_REGISTRY)
        MODEL_REGISTRY.clear()

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



class SupportedOrganismsTests(TestCase):
    def setUp(self):
        self._backup = (dict(MODEL_REGISTRY), dict(MODEL_ORGANISMS))

    def tearDown(self):
        MODEL_REGISTRY.clear()
        MODEL_REGISTRY.update(self._backup[0])
        MODEL_ORGANISMS.clear()
        MODEL_ORGANISMS.update(self._backup[1])

    def test_specific_organisms_are_listed_and_any_organism_models_are_not(self):
        @register_model("test_ecoli")
        class EcoliAdapter:
            supported_organisms = {'NCBITaxon:562': 'Escherichia coli'}

            def __init__(self, antibiotic: str):
                pass

        @register_model("test_tb")
        class TbAdapter:
            supported_organisms = {'NCBITaxon:1773': 'Mycobacterium tuberculosis', 'NCBITaxon:562': 'Escherichia coli'}

            def __init__(self, antibiotic: str):
                pass

        @register_model("test_any")
        class AnyAdapter:
            supported_organisms = ANY_ORGANISM

            def __init__(self, antibiotic: str):
                pass

        self.assertEqual(get_model_supported_organisms('TEST_ECOLI'), {'NCBITaxon:562': 'Escherichia coli'})
        self.assertIs(get_model_supported_organisms('test_any'), ANY_ORGANISM)
        organisms = list_all_organisms()
        self.assertIn(('NCBITaxon:1773', 'Mycobacterium tuberculosis'), organisms)
        names = [name for _, name in organisms]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), len(set(names)))

    def test_models_that_declare_nothing_support_any_organism(self):
        @register_model("test_no_organisms")
        class NoOrganismsAdapter:
            def __init__(self, antibiotic: str):
                pass

        self.assertIs(get_model_supported_organisms('test_no_organisms'), ANY_ORGANISM)

    def test_invalid_organisms_are_rejected(self):
        cases = [['NCBITaxon:562'], {}, {'562': 'Escherichia coli'}, {'NCBITaxon:562': ''}, 'any']
        for organisms in cases:
            with self.subTest(organisms=organisms):
                with self.assertRaises(TypeError):
                    @register_model("test_invalid_organisms")
                    class InvalidAdapter:
                        supported_organisms = organisms

                        def __init__(self, antibiotic: str):
                            pass

    def test_real_models_support_any_organism(self):
        for name in ('base_bakta_50', 'base_bakta_90'):
            if name in self._backup[0]:
                with self.subTest(name):
                    self.assertIs(get_model_supported_organisms(name), ANY_ORGANISM)
