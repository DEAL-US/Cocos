from unittest import mock

from django.test import SimpleTestCase
from rdflib import Graph

from core.models import File
from core.steps import DataKind, Port
from semantics.plugins import DescriptorError, describe_model, describe_parser

GENES = Port('genes', DataKind.GENE_SET, File.FileType.JSON)


class DescribeModelTests(SimpleTestCase):
    def test_reads_ports_organisms_and_antibiotic_names(self):
        description = describe_model('base_bakta_90')

        self.assertEqual(description.inputs, (GENES,))
        self.assertEqual(description.outputs,
                         (Port('predictions', DataKind.RESISTANCE_PREDICTION, File.FileType.CSV),))
        self.assertTrue(description.any_organism)
        self.assertEqual(description.organisms, {})
        self.assertEqual(description.antibiotics, ('amikacin', 'cefotaxime', 'gentamicin'))

    def test_a_term_without_label_asks_to_fetch_the_terms(self):
        with mock.patch('semantics.plugins.terms_graph', return_value=Graph()):
            with self.assertRaisesRegex(DescriptorError, 'fetch_terms'):
                describe_model('base_bakta_50')

    def test_a_model_without_descriptor_is_an_error(self):
        with self.assertRaisesRegex(DescriptorError, 'not found'):
            describe_model('no_such_model')


class DescribeParserTests(SimpleTestCase):
    def test_reads_label_and_ports(self):
        description = describe_parser('bakta_json')

        self.assertEqual(description.label, 'Gene extraction · Bakta JSON')
        self.assertEqual(description.inputs, (Port('annotation', DataKind.ANNOTATED_GENOME, File.FileType.JSON),))
        self.assertEqual(description.outputs, (GENES,))

    def test_a_parser_without_descriptor_is_not_a_step(self):
        self.assertIsNone(describe_parser('no_such_parser'))
