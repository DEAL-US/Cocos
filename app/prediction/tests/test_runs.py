"""Prediction runs through the orchestrator: one task per model, combined into a matrix and a CSV."""
import csv
import io
import json

from django.core.files.base import ContentFile
from django.test import TestCase

from core.models import File, TaskStatus
from core.orchestration import create_process, extend_plan
from core.testing import BAKTA_JSON, FlowTestMixin
from notifications.models import TaskNotification
from prediction.models import PredictionRun
from prediction.prediction import NO_RESULT
from prediction.registry import MODEL_REGISTRY


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
        for name, cls in (('fake_half', HalfModel), ('fake_broken', BrokenModel)):
            MODEL_REGISTRY[name] = cls
            self.addCleanup(MODEL_REGISTRY.pop, name, None)

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
        self.assertEqual(run.data, [[0.25, NO_RESULT], [NO_RESULT, NO_RESULT]])
        self.assertEqual(sorted(task.status for task in run.tasks.all()), [TaskStatus.COMPLETED, TaskStatus.FAILED])

        self.assertEqual(run.output_csv.file_type, File.FileType.CSV)
        with run.output_csv.file.open('rb') as f:
            rows = list(csv.reader(io.StringIO(f.read().decode())))
        self.assertEqual(rows, [['Antibiotic', 'fake_half', 'fake_broken', 'Average'],
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
