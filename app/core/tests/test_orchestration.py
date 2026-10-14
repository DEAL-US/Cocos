"""Process plans run end to end, with Celery running eagerly and the fake bio service."""
import json

from django.core.files.base import ContentFile
from django.test import TestCase

from core.models import File, FileGene, ProcessGroup, Task, TaskStatus
from core.orchestration import PlanError, advance_plan, create_process, extend_plan, latest_tasks, retry_node
from core.testing import BAKTA_JSON, FakeBioService, FlowTestMixin
from notifications.models import TaskNotification
from prediction.models import PredictionRun, PredictionTask
from prediction.adapters.registry import MODEL_REGISTRY


class ConstantModel:
    def __init__(self, antibiotic):
        self.antibiotic = antibiotic

    def load(self):
        pass

    def predict(self, file):
        return 0.5


class OrchestrationTestCase(FlowTestMixin, TestCase):
    def make_file(self, file_type, content, name):
        file = File(user=self.user, file_type=file_type)
        file.file.save(name, ContentFile(content), save=True)
        return file

    def reads(self):
        return self.make_file(File.FileType.FASTQ, b'READS', 'reads.fastq.gz')

    def bakta_json(self, content=None):
        return self.make_file(File.FileType.JSON, content or json.dumps(BAKTA_JSON).encode(), 'sample.json')

    def statuses(self, process):
        return {node_id: task.status for node_id, task in latest_tasks(process).items()}


class PlanExecutionTests(OrchestrationTestCase):
    def test_assembly_with_annotation_then_gene_extraction(self):
        nodes = [
            {'id': 'n1', 'step': 'assembly_ont_annotated'},
            {'id': 'n2', 'step': 'extract_bakta_json', 'after': ['n1'], 'parameters': {'complete_version': True}},
        ]
        with FakeBioService():
            process = create_process(self.user, 'reads.fastq.gz', nodes, {'n1': {'reads': self.reads()}},
                                     organism='NCBITaxon:562')

        process.refresh_from_db()
        self.assertEqual(process.organism, 'NCBITaxon:562')
        self.assertEqual(process.plan, [
            {'id': 'n1', 'step': 'assembly_ont_annotated', 'parameters': {}, 'after': [], 'batch': 1},
            {'id': 'n2', 'step': 'extract_bakta_json', 'parameters': {'complete_version': True}, 'after': ['n1'], 'batch': 1},
        ])
        self.assertEqual(self.statuses(process), {'n1': TaskStatus.COMPLETED, 'n2': TaskStatus.COMPLETED})

        assembly, extraction = latest_tasks(process)['n1'], latest_tasks(process)['n2']
        annotation = assembly.output_file('annotation')
        self.assertEqual(extraction.input_file('annotation'), annotation)
        self.assertEqual(extraction.output_file('genes'), annotation)
        self.assertTrue(FileGene.objects.filter(file=annotation, nt__isnull=False).exists())

    def test_extending_a_plan_runs_only_the_new_nodes(self):
        with FakeBioService() as bio:
            process = create_process(self.user, 'reads', [{'id': 'n1', 'step': 'assembly_ont'}], {'n1': {'reads': self.reads()}})
            launched = extend_plan(process, [
                {'id': 'n2', 'step': 'bakta_annotation', 'after': ['n1']},
                {'id': 'n3', 'step': 'extract_bakta_json', 'after': ['n2']},
            ])

        self.assertEqual([task.plan_node for task in launched], ['n2'])
        self.assertEqual(len(bio.submissions_to('assembly/ont')), 1)
        process.refresh_from_db()
        self.assertEqual([node['batch'] for node in process.plan], [1, 2, 2])
        self.assertEqual(self.statuses(process), {node: TaskStatus.COMPLETED for node in ('n1', 'n2', 'n3')})
        self.assertEqual(latest_tasks(process)['n2'].input_file('assembly'), latest_tasks(process)['n1'].output_file('assembly'))

    def test_prediction_nodes_run_in_parallel_after_the_genes(self):
        MODEL_REGISTRY.update({'fake_a': ConstantModel, 'fake_b': ConstantModel})
        self.addCleanup(MODEL_REGISTRY.pop, 'fake_a', None)
        self.addCleanup(MODEL_REGISTRY.pop, 'fake_b', None)

        process = create_process(self.user, 'sample.json', [{'id': 'n1', 'step': 'extract_bakta_json'}],
                                 {'n1': {'annotation': self.bakta_json()}})
        run = PredictionRun.objects.create(process=process, selected_models=['fake_a', 'fake_b'], selected_antibiotics=['amikacin'])
        extend_plan(process, [
            {'id': f'n{index}', 'step': f'predict_{model}', 'after': ['n1'], 'run': run.pk, 'parameters': {'antibiotics': ['amikacin']}}
            for index, model in ((2, 'fake_a'), (3, 'fake_b'))
        ])

        tasks = PredictionTask.objects.filter(run=run).order_by('plan_node')
        self.assertEqual([(task.plan_node, task.status, task.results) for task in tasks],
                         [('n2', TaskStatus.COMPLETED, {'amikacin': 0.5}), ('n3', TaskStatus.COMPLETED, {'amikacin': 0.5})])

    def test_a_failed_node_stops_the_nodes_that_depend_on_it(self):
        nodes = [{'id': 'n1', 'step': 'assembly_ont'}, {'id': 'n2', 'step': 'bakta_annotation', 'after': ['n1']}]
        with FakeBioService(status_sequence=['running', 'failed']):
            process = create_process(self.user, 'reads', nodes, {'n1': {'reads': self.reads()}})

        self.assertEqual(self.statuses(process), {'n1': TaskStatus.FAILED})

    def test_advancing_again_creates_no_duplicate_tasks(self):
        process = create_process(self.user, 'sample.json', [{'id': 'n1', 'step': 'extract_bakta_json'}],
                                 {'n1': {'annotation': self.bakta_json()}})
        self.assertEqual(advance_plan(process), [])
        self.assertEqual(Task.objects.filter(process=process).count(), 1)

    def test_retrying_a_failed_node_reuses_its_inputs(self):
        with FakeBioService(start_behavior='busy'):
            process = create_process(self.user, 'reads', [{'id': 'n1', 'step': 'assembly_ont'}], {'n1': {'reads': self.reads()}})
        first = latest_tasks(process)['n1']
        first.status = TaskStatus.FAILED
        first.save()

        with FakeBioService():
            retried = retry_node(process, 'n1')

        retried.refresh_from_db()
        self.assertNotEqual(retried.pk, first.pk)
        self.assertEqual(retried.status, TaskStatus.COMPLETED)
        self.assertEqual(retried.input_file('reads'), first.input_file('reads'))
        with self.assertRaises(PlanError):
            retry_node(process, 'n1')


class PlanValidationTests(OrchestrationTestCase):
    def test_invalid_plans_are_rejected_before_creating_anything(self):
        reads = self.reads()
        cases = [
            ('missing id', [{'step': 'assembly_ont'}], {}),
            ('duplicate id', [{'id': 'n1', 'step': 'assembly_ont'}, {'id': 'n1', 'step': 'bakta_annotation'}], {'n1': {'reads': reads}}),
            ('unknown step', [{'id': 'n1', 'step': 'no_such_step'}], {}),
            ('unknown dependency', [{'id': 'n1', 'step': 'bakta_annotation', 'after': ['n0']}], {}),
            ('missing input', [{'id': 'n1', 'step': 'assembly_ont'}], {}),
            ('unknown input role', [{'id': 'n1', 'step': 'assembly_ont'}], {'n1': {'reads': reads, 'r2': reads}}),
            ('input for unknown node', [{'id': 'n1', 'step': 'assembly_ont'}], {'n1': {'reads': reads}, 'n9': {}}),
            ('incompatible dependency', [{'id': 'n1', 'step': 'assembly_ont'},
                                         {'id': 'n2', 'step': 'extract_bakta_json', 'after': ['n1']}], {'n1': {'reads': reads}}),
            ('uploaded file for a dependent node', [{'id': 'n1', 'step': 'assembly_ont'},
                                                    {'id': 'n2', 'step': 'bakta_annotation', 'after': ['n1']}],
             {'n1': {'reads': reads}, 'n2': {'assembly': reads}}),
            ('unknown parameter', [{'id': 'n1', 'step': 'assembly_ont', 'parameters': {'threads': 2}}], {'n1': {'reads': reads}}),
        ]
        for label, nodes, inputs in cases:
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    create_process(self.user, 'p', nodes, inputs)
        self.assertFalse(ProcessGroup.objects.exists())
        self.assertFalse(Task.objects.exists())


class BatchNotificationTests(OrchestrationTestCase):
    def events(self, process):
        return list(TaskNotification.objects.filter(task__process=process).order_by('id').values_list('event_type', 'message'))

    def test_one_started_and_one_completed_per_request(self):
        nodes = [{'id': 'n1', 'step': 'assembly_ont_annotated'}, {'id': 'n2', 'step': 'extract_bakta_json', 'after': ['n1']}]
        with FakeBioService():
            process = create_process(self.user, 'reads.fastq.gz', nodes, {'n1': {'reads': self.reads()}})
            first_request = self.events(process)
            extend_plan(process, [{'id': 'n3', 'step': 'bakta_annotation', 'after': ['n1']},
                                  {'id': 'n4', 'step': 'extract_bakta_json', 'after': ['n3']}])

        self.assertEqual(first_request, [
            (TaskNotification.EVENT_STARTED, 'The Assembly + Annotation · ONT for the process reads.fastq.gz has started and is now running.'),
            (TaskNotification.EVENT_COMPLETED, 'The Assembly + Annotation · ONT for the process reads.fastq.gz is complete. You can now access your results.'),
        ])
        self.assertEqual(self.events(process)[2:], [
            (TaskNotification.EVENT_STARTED, 'The Annotation for the process reads.fastq.gz has started and is now running.'),
            (TaskNotification.EVENT_COMPLETED, 'The Annotation for the process reads.fastq.gz is complete. You can now access your results.'),
        ])

    def test_failures_are_always_notified(self):
        nodes = [{'id': 'n1', 'step': 'assembly_ont'}, {'id': 'n2', 'step': 'bakta_annotation', 'after': ['n1']}]
        with FakeBioService(status_sequence=['running', 'failed']):
            process = create_process(self.user, 'reads', nodes, {'n1': {'reads': self.reads()}})

        self.assertEqual([event for event, _ in self.events(process)],
                         [TaskNotification.EVENT_STARTED, TaskNotification.EVENT_FAILED])

    def test_extraction_failing_after_annotation_only_warns(self):
        nodes = [{'id': 'n1', 'step': 'assembly_ont_annotated'}, {'id': 'n2', 'step': 'extract_bakta_json', 'after': ['n1']}]
        with FakeBioService(annotation_payload={'features': ['not a feature']}):
            process = create_process(self.user, 'reads', nodes, {'n1': {'reads': self.reads()}})

        self.assertEqual(self.statuses(process), {'n1': TaskStatus.COMPLETED, 'n2': TaskStatus.FAILED})
        self.assertEqual([event for event, _ in self.events(process)],
                         [TaskNotification.EVENT_STARTED, TaskNotification.EVENT_WARNING, TaskNotification.EVENT_COMPLETED])

    def test_extraction_of_an_uploaded_file_fails(self):
        process = create_process(self.user, 'bad.json', [{'id': 'n1', 'step': 'extract_bakta_json'}],
                                 {'n1': {'annotation': self.bakta_json(b'{not json')}})

        self.assertEqual(self.events(process), [
            (TaskNotification.EVENT_STARTED, 'The Gene extraction · Bakta JSON for the process bad.json has started and is now running.'),
            (TaskNotification.EVENT_FAILED, 'Error decoding JSON file.'),
        ])

    def test_prediction_requests_notify_their_start_and_end_once(self):
        MODEL_REGISTRY.update({'fake_a': ConstantModel, 'fake_b': ConstantModel})
        self.addCleanup(MODEL_REGISTRY.pop, 'fake_a', None)
        self.addCleanup(MODEL_REGISTRY.pop, 'fake_b', None)
        process = create_process(self.user, 'sample.json', [{'id': 'n1', 'step': 'extract_bakta_json'}],
                                 {'n1': {'annotation': self.bakta_json()}})
        run = PredictionRun.objects.create(process=process, selected_models=['fake_a', 'fake_b'], selected_antibiotics=['amikacin'])
        before = len(self.events(process))

        extend_plan(process, [
            {'id': f'n{index}', 'step': f'predict_{model}', 'after': ['n1'], 'run': run.pk, 'parameters': {'antibiotics': ['amikacin']}}
            for index, model in ((2, 'fake_a'), (3, 'fake_b'))
        ])

        self.assertEqual(self.events(process)[before:], [
            (TaskNotification.EVENT_STARTED, 'The prediction task has started and is now running.'),
            (TaskNotification.EVENT_COMPLETED, 'The prediction task has completed successfully. You can now access your results.'),
        ])
