"""End-to-end prediction flows through the views.

Genes come from a real Bakta JSON upload; models are small fake adapters registered for the
test (plus one smoke test with the real base_bakta_50 model). These tests describe
user-visible behaviour and must keep passing unchanged across internal refactors.
"""
import csv
import io
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import File, ProcessGroup, TaskStatus
from core.testing import BAKTA_JSON, FakeBioService, FlowTestMixin
from prediction.models import PredictionRun
from prediction.adapters.registry import MODEL_ANTIBIOTICS, MODEL_REGISTRY


class ConstantModel:
    value = 0.25

    def __init__(self, antibiotic):
        self.antibiotic = antibiotic

    def load(self):
        pass

    def predict(self, file):
        return self.value if self.antibiotic == 'amikacin' else 1 - self.value


class GeneCountModel(ConstantModel):
    def predict(self, file):
        return file.genes.count() / 10


class BrokenModel(ConstantModel):
    def predict(self, file):
        raise RuntimeError('model exploded')


FAKE_MODELS = {
    'fake_constant': (ConstantModel, ['amikacin', 'ampicillin']),
    'fake_genes': (GeneCountModel, ['amikacin']),
    'fake_broken': (BrokenModel, ['amikacin', 'ampicillin']),
}


class PredictionFlowTests(FlowTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._registry_backup = (dict(MODEL_REGISTRY), dict(MODEL_ANTIBIOTICS))
        for name, (cls, antibiotics) in FAKE_MODELS.items():
            MODEL_REGISTRY[name] = cls
            MODEL_ANTIBIOTICS[name] = antibiotics

        payload = SimpleUploadedFile('sample.json', json.dumps(BAKTA_JSON).encode(), content_type='application/json')
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': payload})
        self.process = ProcessGroup.objects.get(user=self.user)
        self.genes_file = File.objects.get(user=self.user, file_type=File.FileType.JSON)

    def tearDown(self):
        MODEL_REGISTRY.clear()
        MODEL_REGISTRY.update(self._registry_backup[0])
        MODEL_ANTIBIOTICS.clear()
        MODEL_ANTIBIOTICS.update(self._registry_backup[1])
        super().tearDown()

    def predict(self, models, antibiotics, file_id=None):
        return self.client.post(reverse('prediction:prediction_matrix'), data={
            'models': models,
            'antibiotics': antibiotics,
            'file_id': file_id if file_id is not None else self.genes_file.id,
        })

    def predictions_on_status_page(self):
        response = self.client.get(reverse('conversion:process_status', args=[self.process.id]))
        self.assertEqual(response.status_code, 200)
        return response.context['predictions']

    def download_csv(self, prediction_id):
        response = self.client.post(reverse('prediction:download_csv', args=[prediction_id]))
        self.assertEqual(response.status_code, 200)
        content = b''.join(response.streaming_content).decode()
        return list(csv.reader(io.StringIO(content)))

    def test_prediction_page_lists_inputs_models_and_antibiotics(self):
        response = self.client.get(reverse('prediction:prediction'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(self.genes_file.id), [option['id'] for option in response.context['input_file_options']])
        self.assertTrue(set(FAKE_MODELS) <= set(response.context['available_models']))
        self.assertTrue({'amikacin', 'ampicillin'} <= set(response.context['available_antibiotics']))

    def test_files_without_genes_are_not_offered_nor_accepted(self):
        broken = SimpleUploadedFile('broken.json', json.dumps({'features': ['not a feature']}).encode(),
                                    content_type='application/json')
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': broken})
        broken_file = File.objects.get(user=self.user, file_type=File.FileType.JSON, file__contains='broken')

        options = self.client.get(reverse('prediction:prediction')).context['input_file_options']
        self.assertEqual([option['id'] for option in options], [str(self.genes_file.id)])
        self.assertEqual(self.predict(['fake_constant'], ['amikacin'], broken_file.id).status_code, 400)
        self.assertFalse(PredictionRun.objects.exists())

    def test_prediction_with_several_models_builds_matrix_and_csv(self):
        response = self.predict(['fake_constant', 'fake_genes'], ['amikacin', 'ampicillin'])
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['process_id'], self.process.id)

        [prediction] = self.predictions_on_status_page()
        self.assertEqual(prediction['status'], TaskStatus.COMPLETED)
        self.assertTrue(prediction['can_download'])
        self.assertEqual(prediction['matrix']['models'], ['fake_constant', 'fake_genes'])
        self.assertEqual(prediction['matrix']['antibiotics'], ['amikacin', 'ampicillin'])
        n_genes = self.genes_file.genes.count()
        self.assertEqual(prediction['matrix']['data'][0], [0.25, n_genes / 10])
        self.assertEqual(prediction['matrix']['data'][1][0], 0.75)

        rows = self.download_csv(prediction['id'])
        self.assertEqual(rows[0], ['Antibiotic', 'fake_constant', 'fake_genes', 'Average'])
        self.assertEqual(rows[1], ['amikacin', '0.25', str(round(n_genes / 10, 4)), str(round((0.25 + n_genes / 10) / 2, 4))])
        self.assertEqual(rows[2][0], 'ampicillin')
        self.assertEqual(rows[2][1], '0.75')

    def test_failing_model_gives_empty_cell_but_prediction_completes(self):
        self.predict(['fake_constant', 'fake_broken'], ['amikacin'])

        [prediction] = self.predictions_on_status_page()
        self.assertEqual(prediction['status'], TaskStatus.COMPLETED)
        self.assertEqual(prediction['matrix']['data'], [[0.25, 'NO_RESULT']])
        rows = self.download_csv(prediction['id'])
        self.assertEqual(rows[1], ['amikacin', '0.25', '', '0.25'])

    def test_unsupported_antibiotics_are_dropped(self):
        self.predict(['fake_genes'], ['amikacin', 'ampicillin', 'unknown'])
        [prediction] = self.predictions_on_status_page()
        self.assertEqual(prediction['antibiotics'], ['amikacin'])

    def test_invalid_requests_are_rejected(self):
        cases = [
            ('no models', [], ['amikacin'], None),
            ('no antibiotics', ['fake_constant'], [], None),
            ('no valid combination', ['fake_genes'], ['ampicillin'], None),
            ('no file', ['fake_constant'], ['amikacin'], ''),
            ('unknown file', ['fake_constant'], ['amikacin'], 999999),
        ]
        for label, models, antibiotics, file_id in cases:
            with self.subTest(label):
                response = self.predict(models, antibiotics, file_id)
                self.assertEqual(response.status_code, 400)
        self.assertFalse(PredictionRun.objects.exists())

    def test_other_user_cannot_predict_on_or_download_my_results(self):
        self.predict(['fake_constant'], ['amikacin'])
        prediction = PredictionRun.objects.get()

        self.client.login(username='other-user', password='pass1234')
        self.assertEqual(self.predict(['fake_constant'], ['amikacin']).status_code, 400)
        response = self.client.post(reverse('prediction:download_csv', args=[prediction.id]))
        self.assertEqual(response.status_code, 404)

    def test_real_models_smoke(self):
        real_models = {name: antibiotics for name, antibiotics in self._registry_backup[1].items() if antibiotics}
        if not real_models:
            self.skipTest('No real models with weights are registered in this environment')
        MODEL_REGISTRY.update(self._registry_backup[0])
        MODEL_ANTIBIOTICS.update(self._registry_backup[1])

        for name, antibiotics in real_models.items():
            with self.subTest(model=name):
                run_id = self.predict([name], [antibiotics[0]]).json()['run_id']

                [prediction] = [p for p in self.predictions_on_status_page() if p['id'] == run_id]
                self.assertEqual(prediction['status'], TaskStatus.COMPLETED)
                value = prediction['matrix']['data'][0][0]
                self.assertIsInstance(value, float)
                self.assertTrue(0 <= value <= 1)
