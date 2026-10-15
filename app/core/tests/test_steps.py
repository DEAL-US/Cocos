from django.test import SimpleTestCase

from core import steps as step_registry
from unittest import mock

from conversion.parsers import PARSERS, BaseParser, register_parser
from core.models import File, TaskStatus
from core.steps import (
    DataKind,
    ExternalStep,
    LocalStep,
    Port,
    UnknownStepError,
    get_step,
    list_steps,
    register_step,
)
from prediction.adapters.registry import ANY_ORGANISM, MODEL_REGISTRY
from prediction.testing import register_fake_models
from semantics.plugins import ParserDescription

FASTQ, FASTA, JSON = File.FileType.FASTQ, File.FileType.FASTA, File.FileType.JSON


def ports(*triples):
    return tuple(Port(role, kind, file_format) for role, kind, file_format in triples)


class ConversionStepsTests(SimpleTestCase):
    def test_conversion_steps_declare_their_inputs_and_outputs(self):
        reads = ('reads', DataKind.READS, FASTQ)
        pair = (('r1', DataKind.READS, FASTQ), ('r2', DataKind.READS, FASTQ))
        assembly = ('assembly', DataKind.ASSEMBLY, FASTA)
        annotation = ('annotation', DataKind.ANNOTATED_GENOME, JSON)
        cases = [
            ('assembly_ont', 'Assembly · ONT', 'assembly', True, ports(reads), ports(assembly)),
            ('assembly_illumina', 'Assembly · Illumina', 'assembly', True, ports(*pair), ports(assembly)),
            ('assembly_ont_annotated', 'Assembly + Annotation · ONT', 'assembly', True, ports(reads), ports(assembly, annotation)),
            ('assembly_illumina_annotated', 'Assembly + Annotation · Illumina', 'assembly', True, ports(*pair), ports(assembly, annotation)),
            ('bakta_annotation', 'Annotation', 'annotation', True, ports(assembly), ports(annotation)),
            ('extract_bakta_json', 'Gene extraction · Bakta JSON', 'extraction', False, ports(annotation), ports(('genes', DataKind.GENE_SET, JSON))),
        ]
        for key, label, category, is_external, consumes, produces in cases:
            with self.subTest(key):
                step = get_step(key)
                self.assertEqual((step.key, step.label, step.category), (key, label, category))
                self.assertEqual(step.is_external, is_external)
                self.assertEqual(step.consumes, consumes)
                self.assertEqual(step.produces, produces)

    def test_assembly_steps_know_technology_and_auto_annotation(self):
        cases = [
            ('assembly_ont', 'ont', False),
            ('assembly_illumina', 'illumina', False),
            ('assembly_ont_annotated', 'ont', True),
            ('assembly_illumina_annotated', 'illumina', True),
        ]
        for key, technology, annotate in cases:
            with self.subTest(key):
                step = get_step(key)
                self.assertEqual((step.technology, step.annotate), (technology, annotate))

    def test_steps_chain_from_reads_to_genes(self):
        """Each step's output feeds the next one: reads -> assembly -> annotation -> genes -> prediction."""
        chain = [get_step('assembly_ont'), get_step('bakta_annotation'), get_step('extract_bakta_json')]
        for producer, consumer in zip(chain, chain[1:]):
            with self.subTest(f'{producer.key} -> {consumer.key}'):
                produced = {(port.kind, port.format) for port in producer.produces}
                self.assertTrue(all((port.kind, port.format) in produced for port in consumer.consumes))

    def test_parameters_use_defaults_and_reject_unknown_names(self):
        annotation = get_step('bakta_annotation')
        self.assertEqual(annotation.build_parameters(), {'threads': 4})
        self.assertEqual(annotation.build_parameters({'threads': 8}), {'threads': 8})
        with self.assertRaisesRegex(ValueError, 'complete_version'):
            annotation.build_parameters({'complete_version': True})
        self.assertEqual(get_step('extract_bakta_json').build_parameters({'complete_version': True}),
                         {'complete_version': True})

    def test_port_lookup_by_role(self):
        step = get_step('assembly_illumina')
        self.assertEqual(step.input_port('r2'), Port('r2', DataKind.READS, FASTQ))
        self.assertEqual(step.output_port('assembly').kind, DataKind.ASSEMBLY)
        with self.assertRaises(KeyError):
            step.input_port('reads')


class ExternalStatusTests(SimpleTestCase):
    def test_service_statuses_map_to_task_statuses_per_step(self):
        running, completed, failed = TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED
        cases = {
            'assembly_ont': {'pending': running, 'running': running, 'assembled': completed,
                             'completed': completed, 'failed': failed},
            'assembly_illumina_annotated': {'running': running, 'assembled': running, 'annotation_pending': running,
                                            'annotated': completed, 'failed': failed},
            'bakta_annotation': {'annotation_pending': running, 'running': running, 'annotated': completed,
                                 'failed': failed},
        }
        for key, mapping in cases.items():
            step = get_step(key)
            for external_status, expected in mapping.items():
                with self.subTest(step=key, status=external_status):
                    self.assertEqual(step.task_status(external_status), expected)


class GeneExtractionStepsTests(SimpleTestCase):
    def register_parser_temporarily(self, name, cls, description=None):
        with mock.patch('conversion.parsers.describe_parser', return_value=description):
            register_parser(name)(cls)
        self.addCleanup(PARSERS.pop, name, None)

    def test_one_extraction_step_per_parser_with_a_descriptor(self):
        class TsvParser(BaseParser):
            default_options = {'min_identity': 90}

        class UndeclaredParser(BaseParser):
            pass

        description = ParserDescription(
            label='Gene extraction · AMR TSV',
            inputs=ports(('annotation', DataKind.ANNOTATED_GENOME, File.FileType.CSV)),
            outputs=ports(('genes', DataKind.GENE_SET, File.FileType.CSV)),
        )
        self.register_parser_temporarily('test_tsv', TsvParser, description)
        self.register_parser_temporarily('test_undeclared', UndeclaredParser)

        step = get_step('extract_test_tsv')
        self.assertEqual((step.parser_name, step.label, step.category), ('test_tsv', 'Gene extraction · AMR TSV', 'extraction'))
        self.assertEqual(step.consumes, ports(('annotation', DataKind.ANNOTATED_GENOME, File.FileType.CSV)))
        self.assertEqual(step.produces, ports(('genes', DataKind.GENE_SET, File.FileType.CSV)))
        self.assertEqual(step.build_parameters(), {'min_identity': 90})
        with self.assertRaises(UnknownStepError):
            get_step('extract_test_undeclared')


class PredictionStepsTests(SimpleTestCase):
    def register_late_model(self):
        register_fake_models(self, {'late_model': (object, ['amikacin'])})

    def test_one_prediction_step_per_registered_model(self):
        keys = {step.key for step in list_steps() if step.category == 'prediction'}
        self.assertEqual(keys, {f'predict_{name}' for name in MODEL_REGISTRY})

    def test_models_registered_later_are_available_as_steps(self):
        self.register_late_model()

        step = get_step('predict_late_model')

        self.assertIsInstance(step, LocalStep)
        self.assertEqual((step.model_name, step.label, step.category), ('late_model', 'late_model', 'prediction'))
        self.assertEqual(step.consumes, ports(('genes', DataKind.GENE_SET, JSON)))
        self.assertEqual(step.produces, ports(('predictions', DataKind.RESISTANCE_PREDICTION, File.FileType.CSV)))
        self.assertEqual(step.supported_antibiotics, ['amikacin'])
        self.assertIs(step.supported_organisms, ANY_ORGANISM)
        self.assertEqual(step.build_parameters({'antibiotics': ['amikacin']}), {'antibiotics': ['amikacin']})

    def test_default_parameters_are_not_shared_between_calls(self):
        self.register_late_model()
        step = get_step('predict_late_model')
        step.build_parameters()['antibiotics'].append('amikacin')
        self.assertEqual(step.build_parameters(), {'antibiotics': []})

    def test_unregistered_model_has_no_step(self):
        with self.assertRaises(UnknownStepError):
            get_step('predict_not_a_model')


class RegistryTests(SimpleTestCase):
    def register_temporarily(self, cls):
        register_step(cls)
        self.addCleanup(step_registry._STEPS.pop, cls.key, None)

    def test_unknown_step(self):
        with self.assertRaises(UnknownStepError):
            get_step('does_not_exist')

    def test_every_step_is_valid(self):
        for step in list_steps():
            with self.subTest(step.key):
                step_registry.validate_step(step)

    def test_register_and_get(self):
        class Dummy(LocalStep):
            key = 'test_dummy'
            label = 'Dummy'
            category = 'test'

        self.register_temporarily(Dummy)
        self.assertIsInstance(get_step('test_dummy'), Dummy)
        self.assertIn('test_dummy', {step.key for step in list_steps()})

    def test_invalid_steps_are_rejected(self):
        class NoKey(LocalStep):
            label = 'No key'
            category = 'test'

        class SameRoleTwice(ExternalStep):
            key = 'test_same_role'
            label = 'Same role'
            category = 'test'
            consumes = ports(('reads', DataKind.READS, FASTQ), ('reads', DataKind.READS, FASTQ))

        class UnknownFormat(LocalStep):
            key = 'test_unknown_format'
            label = 'Unknown format'
            category = 'test'
            produces = ports(('out', DataKind.ASSEMBLY, 'bam'))

        for cls in (NoKey, SameRoleTwice, UnknownFormat):
            with self.subTest(cls.__name__):
                with self.assertRaises(TypeError):
                    register_step(cls)
                self.assertNotIn(cls.key, step_registry._STEPS)

    def test_duplicate_key_is_rejected(self):
        class First(LocalStep):
            key = 'test_duplicate'
            label = 'First'
            category = 'test'

        class Second(First):
            label = 'Second'

        self.register_temporarily(First)
        with self.assertRaises(ValueError):
            register_step(Second)
        self.assertIsInstance(get_step('test_duplicate'), First)
