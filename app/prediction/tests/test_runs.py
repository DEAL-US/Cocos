"""Prediction runs through the orchestrator: one task per model, combined into a matrix and a CSV."""
import csv
import io
import json

from django.core.files.base import ContentFile
from django.test import TestCase

from core.models import File, TaskStatus
from conversion.tests.test_flows import ConversionFlowMixin
from core.orchestration import create_process, extend_plan
from core.testing import BAKTA_JSON, FakeBioService, FlowTestMixin
from notifications.models import TaskNotification
from prediction.models import NO_RESULT, PredictionRun
from prediction.testing import register_fake_models
from prediction.runs import prepare_prediction_csv


class HalfModel:
    def __init__(self, antibiotic):
        self.antibiotic = antibiotic

    def load(self):
        pass

    def predict(self, file):
        if self.antibiotic == 'colistin':
            raise RuntimeError('no weights for colistin')
        return 0.25


class BrokenModel(HalfModel):
    def predict(self, file):
        raise RuntimeError('model exploded')


class PredictionRunTests(FlowTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        register_fake_models(self, {'fake_half': HalfModel, 'fake_broken': BrokenModel})

        genes = File(user=self.user, file_type=File.FileType.JSON)
        genes.file.save('sample.json', ContentFile(json.dumps(BAKTA_JSON).encode()), save=True)
        self.process = create_process(self.user, 'sample.json', [{'id': 'genes', 'step': 'extract_bakta_json'}],
                                      {'genes': {'annotation': genes}})

    def predict(self, models, antibiotics):
        run = PredictionRun.objects.create(process=self.process, selected_models=models, selected_antibiotics=antibiotics)
        extend_plan(self.process, [
            {'id': f'run{run.pk}_{model}', 'step': f'predict_{model}', 'after': ['genes'], 'run': run.pk,
             'parameters': {'antibiotics': antibiotics}}
            for model in models
        ])
        run.refresh_from_db()
        return run

    def notifications(self):
        return list(TaskNotification.objects.filter(task__process=self.process).order_by('id')
                    .values_list('event_type', 'message'))

    def test_run_combines_every_model_into_a_matrix_and_a_csv(self):
        before = len(self.notifications())
        run = self.predict(['fake_half', 'fake_broken'], ['amikacin', 'colistin'])

        self.assertEqual(run.status, TaskStatus.COMPLETED)
        self.assertEqual(run.data, [[{'score': 0.25}, NO_RESULT], [NO_RESULT, NO_RESULT]])
        self.assertEqual(sorted(task.status for task in run.tasks.all()), [TaskStatus.COMPLETED, TaskStatus.FAILED])

        self.assertEqual(run.output_csv.file_type, File.FileType.CSV)
        with run.output_csv.file.open('rb') as f:
            rows = list(csv.reader(io.StringIO(f.read().decode())))
        self.assertEqual(rows, [['Antibiotic', 'fake_half', 'fake_broken', 'Average probability'],
                                ['amikacin', '0.25', '', '0.25'],
                                ['colistin', '', '', '']])

        self.assertEqual(self.notifications()[before:], [
            (TaskNotification.EVENT_STARTED, 'The prediction task has started and is now running.'),
            (TaskNotification.EVENT_FAILED, 'The model fake_broken could not predict any of the selected antibiotics.'),
            (TaskNotification.EVENT_COMPLETED, 'The prediction task has completed successfully. You can now access your results.'),
        ])

    def test_each_run_is_independent(self):
        first = self.predict(['fake_half'], ['amikacin'])
        second = self.predict(['fake_half'], ['amikacin'])

        self.assertEqual((first.status, second.status), (TaskStatus.COMPLETED, TaskStatus.COMPLETED))
        self.assertNotEqual(first.output_csv, second.output_csv)
        self.assertEqual(first.tasks.count(), 1)
        self.assertEqual(second.tasks.count(), 1)


class PreparePredictionCsvTests(TestCase):
    def test_rounds_values_blanks_missing_and_averages(self):
        matrix = {
            "models": ["a", "b"],
            "antibiotics": ["amikacin", "ampicillin", "colistin"],
            "data": [[{"score": 0.123456}, {"score": 0.5}], [{"score": 0.2}, "NO_RESULT"], ["NO_RESULT", None]],
        }

        models, rows = prepare_prediction_csv(matrix)

        self.assertEqual(models, ["a", "b"])
        self.assertEqual(rows, [
            ["amikacin", 0.1235, 0.5, 0.3117],
            ["ampicillin", 0.2, "", 0.2],
            ["colistin", "", "", ""],
        ])

    def test_shows_calls_and_averages_only_the_probabilities(self):
        matrix = {
            "models": ["ml", "rules"],
            "antibiotics": ["amikacin", "colistin"],
            "data": [[{"score": 0.8}, {"call": "R"}], ["NO_RESULT", {"call": "not_detected"}]],
        }

        _, rows = prepare_prediction_csv(matrix)

        self.assertEqual(rows, [["amikacin", 0.8, "R", 0.8], ["colistin", "", "Not detected", ""]])

    def test_rejects_malformed_matrices(self):
        cases = [
            ("not a dict", []),
            ("missing keys", {"models": ["a"]}),
            ("row count mismatch", {"models": ["a"], "antibiotics": ["x", "y"], "data": [[0.1]]}),
            ("column count mismatch", {"models": ["a", "b"], "antibiotics": ["x"], "data": [[0.1]]}),
        ]
        for label, matrix in cases:
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    prepare_prediction_csv(matrix)


class PredictionAfterPreparationTests(ConversionFlowMixin, TestCase):
    """Predictions can wait for preparation steps added to the plan in the same request."""

    def setUp(self):
        super().setUp()
        register_fake_models(self, {'fake_half': HalfModel, 'fake_other': HalfModel})
        with FakeBioService():
            self.run_assembly('ont', annotate=True)  # n1: assembly + annotation, n2: gene extraction
        self.process = self.latest_process()

    def predict(self, preparation_behavior=None):
        """fake_half on the genes the process has; fake_other after annotating the assembly again."""
        run = PredictionRun.objects.create(process=self.process, selected_models=['fake_half', 'fake_other'],
                                           selected_antibiotics=['amikacin'])
        parameters = {'antibiotics': ['amikacin']}
        with FakeBioService(**(preparation_behavior or {})):
            extend_plan(self.process, [
                {'id': 'ready', 'step': 'predict_fake_half', 'after': ['n2'], 'run': run.pk, 'parameters': parameters},
                {'id': 'annotate', 'step': 'bakta_annotation', 'after': ['n1']},
                {'id': 'extract', 'step': 'extract_bakta_json', 'after': ['annotate']},
                {'id': 'prepared', 'step': 'predict_fake_other', 'after': ['extract'], 'run': run.pk,
                 'parameters': parameters},
            ])
        run.refresh_from_db()
        self.process.refresh_from_db()
        return run

    def test_the_run_waits_for_the_models_whose_preparation_is_running(self):
        run = self.predict()

        self.assertEqual(run.status, TaskStatus.COMPLETED)
        self.assertEqual(run.data, [[{'score': 0.25}, {'score': 0.25}]])

    def test_a_failed_preparation_cancels_its_prediction_and_the_others_keep_their_results(self):
        run = self.predict({'status_sequence': ['failed']})

        self.assertEqual(run.status, TaskStatus.COMPLETED)
        self.assertEqual(run.data, [[{'score': 0.25}, NO_RESULT]])
        cancelled = {node['id'] for node in self.process.plan if node.get('cancelled')}
        self.assertEqual(cancelled, {'prepared'})  # the extraction stays, so the annotation can be retried

    def test_the_run_fails_when_every_preparation_fails(self):
        run = PredictionRun.objects.create(process=self.process, selected_models=['fake_other'],
                                           selected_antibiotics=['amikacin'])
        with FakeBioService(status_sequence=['failed']):
            extend_plan(self.process, [
                {'id': 'annotate', 'step': 'bakta_annotation', 'after': ['n1']},
                {'id': 'extract', 'step': 'extract_bakta_json', 'after': ['annotate']},
                {'id': 'prepared', 'step': 'predict_fake_other', 'after': ['extract'], 'run': run.pk,
                 'parameters': {'antibiotics': ['amikacin']}},
            ])
        run.refresh_from_db()

        self.assertEqual(run.status, TaskStatus.FAILED)
        messages = TaskNotification.objects.filter(task__process=self.process).values_list('message', flat=True)
        self.assertIn('The prediction could not run because a preparation step failed.', messages)
