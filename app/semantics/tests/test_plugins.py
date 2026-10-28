import hashlib
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from rdflib import Graph

from core.models import File
from core.steps import DataKind, Port
from semantics.checks import check_rejected_plugins
from semantics.registry.descriptors import load_descriptor, model_descriptor_path
from semantics.namespaces import SCHEMA
from semantics.registry.plugins import REJECTED_PLUGINS, DescriptorError, check_files, describe_model, describe_parser

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

    def test_reads_the_version_of_the_model(self):
        self.assertEqual(describe_model('base_bakta_50').version, '1.0.0')

    def test_reads_the_organisms_its_data_is_about(self):
        organisms = describe_model('base_bakta_50').data_organisms
        self.assertEqual(organisms['NCBITaxon:28901'], 'Salmonella enterica')
        self.assertNotIn('NCBITaxon:2', organisms)  # Bacteria means any organism, not data about it

    def test_a_term_without_label_asks_to_fetch_the_terms(self):
        with mock.patch('semantics.registry.plugins.terms_graph', return_value=Graph()):
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


class InvalidDescriptorTests(SimpleTestCase):
    def test_a_descriptor_that_breaks_the_shapes_is_an_error(self):
        graph = load_descriptor(model_descriptor_path('base_bakta_50'))
        graph.remove((None, SCHEMA.url, None))

        with mock.patch('semantics.registry.plugins.load_descriptor', return_value=graph):
            with self.assertRaisesRegex(DescriptorError, 'schema:url'):
                describe_model('base_bakta_50')


class RejectedPluginsCheckTests(SimpleTestCase):
    def test_rejected_plugins_are_reported_as_warnings(self):
        with mock.patch.dict(REJECTED_PLUGINS, {('model', 'broken'): 'no descriptor'}, clear=True):
            messages = check_rejected_plugins(None)

        self.assertEqual([(message.id, message.msg) for message in messages],
                         [('semantics.W001', 'The model broken was not registered: no descriptor')])


class PluginFilesTests(SimpleTestCase):
    def test_the_descriptor_declares_the_weights_of_each_antibiotic(self):
        files = dict(describe_model('base_bakta_50').files)
        self.assertEqual(set(files), {'weights/amikacin.pt', 'weights/cefotaxime.pt', 'weights/meropenem.pt'})
        self.assertTrue(all(len(sha256) == 64 for sha256 in files.values()))
        self.assertIn(('amikacin', 'weights/amikacin.pt'), describe_model('base_bakta_50').weights)

    def test_a_file_must_be_there_and_be_the_one_declared(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'weights').mkdir()
            (Path(folder) / 'weights' / 'amikacin.pt').write_bytes(b'WEIGHTS')
            declared = hashlib.sha256(b'WEIGHTS').hexdigest()

            check_files(folder, [('weights/amikacin.pt', declared)])  # the same file: no error
            with self.assertRaisesRegex(DescriptorError, 'SHA-256 differs'):
                check_files(folder, [('weights/amikacin.pt', hashlib.sha256(b'OTHER').hexdigest())])
            with self.assertRaisesRegex(DescriptorError, 'not in'):
                check_files(folder, [('weights/meropenem.pt', declared)])
