"""Models that run in a service: their descriptor says where, and their jobs go to the model service."""
from unittest import mock

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase
from rdflib import BNode, Literal
from rdflib.namespace import RDF

from core.models import File, TaskStatus
from core.orchestration import create_process, extend_plan
from core.steps import Busy, get_step
from core.testing import ASSEMBLY_FASTA, FlowTestMixin
from prediction import remote
from prediction.adapters import registry
from prediction.models import NO_RESULT, PredictionRun, PredictionTask
from prediction.testing import FakeModelService, register_fake_models, register_fake_remote_models
from semantics.namespaces import SCHEMA
from semantics.registry.descriptors import load_descriptor, model_descriptor_path, model_iri
from semantics.registry.plugins import REJECTED_PLUGINS, DescriptorError, describe_model


def descriptor_with_action(model, method='POST', template='predict/remote_model'):
    """The descriptor of `model`, saying that it runs in a service."""
    graph = load_descriptor(model_descriptor_path(model))
    action, target = BNode(), BNode()
    graph.add((model_iri(model), SCHEMA.potentialAction, action))
    graph.add((action, RDF.type, SCHEMA.Action))
    graph.add((action, SCHEMA.target, target))
    graph.add((target, RDF.type, SCHEMA.EntryPoint))
    graph.add((target, SCHEMA.urlTemplate, Literal(template)))
    graph.add((target, SCHEMA.httpMethod, Literal(method)))
    return graph


class RemoteDescriptorTests(SimpleTestCase):
    def test_reads_where_a_model_runs(self):
        with mock.patch('semantics.registry.plugins.load_descriptor', return_value=descriptor_with_action('base_bakta_50')):
            self.assertEqual(describe_model('base_bakta_50').endpoint, 'predict/remote_model')

    def test_a_model_without_action_runs_in_cocos(self):
        self.assertEqual(describe_model('base_bakta_50').endpoint, '')

    def test_an_entry_point_is_called_with_post(self):
        with mock.patch('semantics.registry.plugins.load_descriptor',
                        return_value=descriptor_with_action('base_bakta_50', method='GET')):
            with self.assertRaisesRegex(DescriptorError, 'httpMethod'):
                describe_model('base_bakta_50')


class RegisterRemoteModelTests(TestCase):
    def setUp(self):
        register_fake_models(self, {})  # the registries are restored after each test
        patcher = mock.patch.dict(REJECTED_PLUGINS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_descriptor_that_says_where_it_runs_registers_a_remote_model(self):
        with mock.patch('semantics.registry.plugins.load_descriptor', return_value=descriptor_with_action('base_bakta_50')):
            registry.register_remote_model('base_bakta_50')

        self.assertEqual(registry.get_model_endpoint('base_bakta_50'), 'predict/remote_model')
        self.assertIsNone(registry.get_model_adapter_class('base_bakta_50'))
        self.assertEqual(type(get_step('predict_base_bakta_50')).__name__, 'RemoteModelPredictionStep')

    def test_a_model_without_code_must_say_where_it_runs(self):
        registry.register_remote_model('base_bakta_50')

        self.assertIn('potentialAction', REJECTED_PLUGINS[('model', 'base_bakta_50')])

    def test_a_model_with_an_adapter_cannot_also_run_in_a_service(self):
        class Adapter:
            def __init__(self, antibiotic):
                pass

        with mock.patch('semantics.registry.plugins.load_descriptor', return_value=descriptor_with_action('base_bakta_50')):
            registry.register_model('base_bakta_50')(Adapter)

        self.assertIn('runs in a service', REJECTED_PLUGINS[('model', 'base_bakta_50')])


class ServiceUrlTests(SimpleTestCase):
    def test_a_relative_endpoint_is_in_the_model_service(self):
        with mock.patch.object(remote, 'BASE', 'http://model-api:8000'):
            self.assertEqual(remote._url('predict/amrfinderplus', 'jobs/1'), 'http://model-api:8000/jobs/1')
            self.assertEqual(remote._url('predict/amrfinderplus', 'predict/amrfinderplus'),
                             'http://model-api:8000/predict/amrfinderplus')

    def test_an_absolute_endpoint_is_its_own_service(self):
        self.assertEqual(remote._url('http://kover:8000/predict/kover', 'jobs/1'), 'http://kover:8000/jobs/1')


RESULTS = [
    {'about': 'ARO:0000013', 'call': 'R', 'evidence': [{'gene': "aac(6')-Ib", 'identity': 99.1}]},  # amikacin
    {'about': 'ARO:3000645', 'score': 0.3},                                                    # cefotaxime
    {'about': 'ARO:0000020', 'call': 'R'},                   # a class of antibiotics: left out until phase 4
]


class RemotePredictionFlowTests(FlowTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        register_fake_remote_models(self, {'fake_remote': ['amikacin', 'cefotaxime', 'meropenem']})
        assembly = File(user=self.user, file_type=File.FileType.FASTA)
        assembly.file.save('sample.fasta', ContentFile(ASSEMBLY_FASTA), save=True)
        self.process = create_process(self.user, 'sample.fasta', [], organism='NCBITaxon:562')
        self.assembly = assembly

    def predict(self, antibiotics=('amikacin', 'cefotaxime', 'meropenem')):
        run = PredictionRun.objects.create(process=self.process, selected_models=['fake_remote'],
                                           selected_antibiotics=list(antibiotics))
        node = f'run{run.pk}_fake_remote'
        extend_plan(self.process, [{'id': node, 'step': 'predict_fake_remote', 'after': [], 'run': run.pk,
                                    'parameters': {'antibiotics': list(antibiotics)}}],
                    {node: {'assembly': self.assembly}})
        run.refresh_from_db()
        return run, PredictionTask.objects.get(run=run)

    def test_sends_the_inputs_and_organism_and_keeps_the_results_of_the_service(self):
        with FakeModelService(results={'fake_remote': RESULTS}) as service:
            run, task = self.predict()

        [submission] = service.submissions
        self.assertEqual(submission['model'], 'fake_remote')
        self.assertEqual(submission['parts']['assembly'], ASSEMBLY_FASTA)
        self.assertEqual(submission['parts']['organism'], b'NCBITaxon:562')

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.results, {'amikacin': {'call': 'R', 'evidence': [{'gene': "aac(6')-Ib", 'identity': 99.1}]},
                                        'cefotaxime': {'score': 0.3},
                                        'meropenem': NO_RESULT})
        self.assertEqual(run.status, TaskStatus.COMPLETED)
        self.assertEqual(run.data, [[task.results['amikacin']], [{'score': 0.3}], [NO_RESULT]])

    def test_keeps_the_output_of_the_tool_and_the_software_its_job_used(self):
        with FakeModelService(results={'fake_remote': RESULTS}):
            _, task = self.predict()

        with task.output_file('tool_output').file.open('rb') as f:
            self.assertEqual(f.read(), FakeModelService.RAW_OUTPUT)
        self.assertEqual(task.output_file('tool_output').file_type, File.FileType.JSON)
        self.assertEqual(task.output_file('predictions').file_type, File.FileType.CSV)
        self.assertEqual([entry['name'] for entry in task.software], ['Cocos', 'fake_remote', 'FakeTool', 'FakeTool database'])

    def test_a_job_that_fails_on_its_input_fails_for_good(self):
        with FakeModelService(results={'fake_remote': RESULTS}, status_sequence=('running', 'failed')):
            run, task = self.predict()

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.error, 'The tool failed on its input')
        self.assertEqual(run.data, [[NO_RESULT]] * 3)

    def test_a_busy_service_does_not_start_the_job(self):
        step = get_step('predict_fake_remote')
        task = PredictionTask(process=self.process, step=step.key)
        with FakeModelService(busy=True), mock.patch.object(PredictionTask, 'input_file', return_value=self.assembly):
            self.assertIsInstance(step.process(task), Busy)

    def test_expects_the_software_the_service_has_installed(self):
        with FakeModelService(results={'fake_remote': RESULTS}):
            software = get_step('predict_fake_remote').expected_software()

        self.assertEqual([entry['name'] for entry in software], ['fake_remote', 'FakeTool', 'FakeTool database'])
