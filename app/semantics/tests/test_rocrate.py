import io
import json
import tempfile
import zipfile

from django.test import TestCase
from django.urls import reverse
from rocrate_validator import models as validator_models
from rocrate_validator import services as validator

from conversion.tests.test_flows import ConversionFlowMixin
from core.testing import FakeBioService
from prediction.models import PredictionRun
from prediction.testing import register_fake_models
from prediction.tests.test_flows import FAKE_MODELS
from semantics.rocrate import METADATA_FILE, PROCESS_RUN_CRATE, PROVENANCE_FILE


class PredictionCrateTests(ConversionFlowMixin, TestCase):
    """A prediction as an RO-Crate: its files and the steps that led to it (Process Run Crate)."""

    def setUp(self):
        super().setUp()
        register_fake_models(self, FAKE_MODELS)
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        self.process = self.latest_process()
        self.client.post(reverse('prediction:prediction_matrix'), data={
            'models': ['fake_constant', 'fake_genes'], 'antibiotics': ['amikacin'], 'sample_id': self.process.id})
        self.run = PredictionRun.objects.get(process=self.process)
        self.url = reverse('semantics:prediction_crate', args=[self.process.id, self.run.id])

    def crate(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        content = b''.join(response.streaming_content)
        archive = zipfile.ZipFile(io.BytesIO(content))
        metadata = json.loads(archive.read(METADATA_FILE))
        return archive, content, {entity['@id']: entity for entity in metadata['@graph']}

    def test_the_crate_has_every_file_from_the_reads_to_the_matrix(self):
        archive, _, entities = self.crate()
        names = set(archive.namelist())

        self.assertIn(PROVENANCE_FILE, names)
        self.assertTrue(any(name.endswith('.fasta') for name in names))
        self.assertTrue(any(name.endswith('.json') and name != METADATA_FILE for name in names))
        self.assertEqual(sum(name.startswith('prediction_') for name in names), 3)  # one per model, and the matrix
        [reads] = [name for name in names if name.endswith('.fastq.gz')]
        self.assertEqual(archive.read(reads), b'R1-CONTENT')
        self.assertEqual(archive.getinfo(reads).compress_type, zipfile.ZIP_STORED)  # compressed already
        for info in archive.infolist():  # each file keeps its date, not the earliest a zip can store
            self.assertGreaterEqual(info.date_time[0], 2026, info.filename)
        for name in names - {METADATA_FILE, PROVENANCE_FILE}:
            self.assertEqual(entities[name]['@type'], 'File')
            self.assertIn('sha256', entities[name])
            self.assertIn({'@id': name}, entities['./']['hasPart'])

    def test_each_step_that_led_to_the_prediction_is_an_action_with_its_software(self):
        _, _, entities = self.crate()
        root = entities['./']
        self.assertEqual(root['conformsTo'], {'@id': PROCESS_RUN_CRATE})
        actions = [entities[mention['@id']] for mention in root['mentions']]

        self.assertEqual([action['name'] for action in actions],
                         ['Assembly + Annotation · ONT', 'Gene extraction · Bakta JSON', 'fake_constant', 'fake_genes',
                          'Prediction matrix'])
        assembly = actions[0]
        software = {entities[item['@id']]['name']: entities[item['@id']] for item in assembly['instrument']}
        self.assertEqual(software['Raven']['softwareVersion'], '1.8.3')
        self.assertEqual(software['Bakta']['url'], 'https://bio.tools/bakta')
        self.assertIn({'@id': 'https://doi.org/10.5281/zenodo.14916843'}, assembly['object'])
        self.assertEqual(assembly['actionStatus'], {'@id': 'http://schema.org/CompletedActionStatus'})
        genes = actions[1]['result'][0]['@id']
        self.assertEqual(entities[genes]['isBasedOn'], actions[0]['result'][1])  # from the annotation
        self.assertEqual(actions[2]['object'], [{'@id': genes}])
        self.assertEqual(entities[actions[4]['result'][0]['@id']]['@type'], 'File')

    def test_the_crate_follows_ro_crate_and_the_process_run_crate_profile(self):
        _, content, _ = self.crate()
        with tempfile.TemporaryDirectory() as folder:
            zipfile.ZipFile(io.BytesIO(content)).extractall(folder)
            result = validator.validate(validator.ValidationSettings(
                rocrate_uri=folder, profile_identifier='process-run-crate',
                requirement_severity=validator_models.Severity.REQUIRED))

        self.assertEqual([f'{issue.check.identifier}: {issue.message}' for issue in result.get_issues()], [])

    def test_only_the_owner_gets_completed_predictions(self):
        self.client.login(username='other-user', password='pass1234')
        self.assertEqual(self.client.get(self.url).status_code, 404)

        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_the_page_of_the_process_offers_it(self):
        self.assertContains(self.client.get(reverse('conversion:process_status', args=[self.process.id])), self.url)
