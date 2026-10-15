from django.test import SimpleTestCase
from rdflib import Literal
from rdflib.namespace import RDF

from conversion.parsers import PARSERS
from prediction.adapters.registry import list_registered_models
from semantics.descriptors import load_descriptor, model_descriptor_path, model_iri, parser_descriptor_path
from semantics.namespaces import COCOS, SCHEMA


class DescriptorTests(SimpleTestCase):
    def test_every_model_has_a_descriptor_of_itself(self):
        for name in list_registered_models():
            with self.subTest(model=name):
                graph = load_descriptor(model_descriptor_path(name))
                self.assertIn((model_iri(name), RDF.type, SCHEMA.SoftwareApplication), graph)
                self.assertEqual(graph.value(model_iri(name), SCHEMA.identifier), Literal(name))

    def test_every_parser_has_a_descriptor_of_its_extraction_step(self):
        for name in PARSERS:
            with self.subTest(parser=name):
                step = COCOS[f'step/extract_{name}']
                graph = load_descriptor(parser_descriptor_path(name))
                self.assertIn((step, RDF.type, SCHEMA.SoftwareApplication), graph)
                self.assertEqual(graph.value(step, SCHEMA.identifier), Literal(f'extract_{name}'))
