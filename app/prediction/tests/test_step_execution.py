"""Prediction steps run on their own, with small fake models."""
import csv
import io
import json

from django.core.files.base import ContentFile
from django.test import TestCase

from conversion.parsers import parse_file
from core.models import File, ProcessGroup
from core.steps import StepError, get_step
from core.testing import BAKTA_JSON, FlowTestMixin
from prediction.models import PredictionRun, PredictionTask
from prediction.prediction import NO_RESULT
from prediction.registry import MODEL_ANTIBIOTICS, MODEL_REGISTRY


class HalfModel:
    def __init__(self, antibiotic):
        self.antibiotic = antibiotic

    def load(self):
        pass

    def predict(self, file):
        if self.antibiotic == 'colistin':
            raise RuntimeError('no weights for colistin')
        return 0.123456 if self.antibiotic == 'amikacin' else file.genes.count() / 10


class BrokenModel(HalfModel):
    def predict(self, file):
        raise RuntimeError('model exploded')


class PredictionStepTests(FlowTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._registry_backup = (dict(MODEL_REGISTRY), dict(MODEL_ANTIBIOTICS))
        self.addCleanup(self._restore_registry)
        MODEL_REGISTRY.update({'fake_half': HalfModel, 'fake_broken': BrokenModel})

        self.process = ProcessGroup.objects.create(name='sample', user=self.user)
        self.genes = File(user=self.user, file_type=File.FileType.JSON)
        self.genes.file.save('genes.json', ContentFile(json.dumps(BAKTA_JSON).encode()), save=True)
        parse_file('bakta_json', BAKTA_JSON, self.genes, user=self.user)

    def _restore_registry(self):
        MODEL_REGISTRY.clear()
        MODEL_REGISTRY.update(self._registry_backup[0])
        MODEL_ANTIBIOTICS.clear()
        MODEL_ANTIBIOTICS.update(self._registry_backup[1])

    def make_task(self, model, antibiotics):
        step = get_step(f'predict_{model}')
        run = PredictionRun.objects.create(process=self.process, selected_models=[model], selected_antibiotics=antibiotics)
        task = PredictionTask.objects.create(process=self.process, step=step.key, run=run,
                                             parameters=step.build_parameters({'antibiotics': antibiotics}))
        task.add_input('genes', self.genes)
        return task

    def test_predicts_each_antibiotic_and_stores_results_and_csv(self):
        task = self.make_task('fake_half', ['amikacin', 'ampicillin', 'colistin'])

        task.get_step().process(task)

        task.refresh_from_db()
        n_genes = self.genes.genes.count()
        self.assertEqual(task.results, {'amikacin': 0.123456, 'ampicillin': n_genes / 10, 'colistin': NO_RESULT})
        with task.output_file('predictions').file.open('rb') as f:
            rows = list(csv.reader(io.StringIO(f.read().decode())))
        self.assertEqual(rows, [['antibiotic', 'probability'], ['amikacin', '0.1235'],
                                ['ampicillin', str(round(n_genes / 10, 4))], ['colistin', '']])

    def test_a_model_that_predicts_nothing_fails_but_keeps_its_results(self):
        task = self.make_task('fake_broken', ['amikacin', 'ampicillin'])

        with self.assertRaisesMessage(StepError, 'fake_broken'):
            task.get_step().process(task)

        task.refresh_from_db()
        self.assertEqual(task.results, {'amikacin': NO_RESULT, 'ampicillin': NO_RESULT})
        self.assertFalse(task.task_outputs.exists())
