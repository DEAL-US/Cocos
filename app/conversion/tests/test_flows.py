"""End-to-end conversion flows through the views, with the bio service mocked at HTTP level.

These tests describe user-visible behaviour (what gets created, stored and notified).
"""
import hashlib
import json
import zipfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from conversion.models import ConversionTask
from core.models import File, FileGene, ProcessGroup, TaskStatus
from core.testing import ASSEMBLY_FASTA, BAKTA_JSON, FakeBioService, FlowTestMixin
from notifications.models import TaskNotification
from prediction.adapters.registry import MODEL_ORGANISMS

N_FEATURES = len(BAKTA_JSON['features'])


def fastq(name='reads.fastq.gz', content=b'@r1\nACGT\n+\nIIII\n'):
    return SimpleUploadedFile(name, content, content_type='application/gzip')


def fasta(name='genome.fasta', content=b'>seq\nACGTACGT\n'):
    return SimpleUploadedFile(name, content, content_type='application/octet-stream')


def bakta_json(name='sample.json', payload=None):
    body = json.dumps(BAKTA_JSON if payload is None else payload).encode()
    return SimpleUploadedFile(name, body, content_type='application/json')


class ConversionFlowMixin(FlowTestMixin):
    def run_assembly(self, assembly_type='ont', annotate=False, complete=False, files=None):
        data = {'assembly_type': assembly_type}
        if files is None:
            files = [fastq('reads_R1.fastq.gz', b'R1-CONTENT')]
            if assembly_type == 'illumina':
                files.append(fastq('reads_R2.fastq.gz', b'R2-CONTENT'))
        data['fastq_file'] = files[0]
        if len(files) > 1:
            data['fastq_file_2'] = files[1]
        if annotate:
            data['annotate'] = 'on'
        if complete:
            data['complete'] = 'on'
        return self.client.post(reverse('conversion:assembly_run'), data=data)

    def latest_process(self):
        return ProcessGroup.objects.filter(user=self.user).order_by('-id').first()

    def process_tasks(self, process):
        return ConversionTask.objects.filter(process=process).order_by('id')

    def process_outputs(self, process, file_type):
        return File.objects.filter(produced_by_tasks__process=process, file_type=file_type).distinct()

    def events(self, process):
        return set(TaskNotification.objects.filter(task__process=process).values_list('event_type', flat=True))


class AssemblyFlowTests(ConversionFlowMixin, TestCase):
    def test_ont_assembly_without_annotation_produces_fasta(self):
        with FakeBioService() as bio:
            response = self.run_assembly('ont')

        process = self.latest_process()
        self.assertRedirects(response, reverse('conversion:process_status', args=[process.id]), fetch_redirect_response=False)
        self.assertEqual(process.name, 'reads_R1.fastq.gz')

        submissions = bio.submissions_to('assembly/ont')
        self.assertEqual(len(submissions), 1)
        self.assertFalse(submissions[0]['annotate'])
        self.assertEqual(submissions[0]['files']['reads'], b'R1-CONTENT')

        tasks = self.process_tasks(process)
        self.assertTrue(all(task.status == TaskStatus.COMPLETED for task in tasks))
        fasta_outputs = self.process_outputs(process, File.FileType.FASTA)
        self.assertEqual(fasta_outputs.count(), 1)
        with fasta_outputs.first().file.open('rb') as f:
            self.assertEqual(f.read(), ASSEMBLY_FASTA)
        self.assertFalse(self.process_outputs(process, File.FileType.JSON).exists())
        self.assertTrue({TaskNotification.EVENT_STARTED, TaskNotification.EVENT_COMPLETED} <= self.events(process))

    def test_illumina_assembly_with_annotation_uses_single_auto_annotated_job(self):
        with FakeBioService() as bio:
            self.run_assembly('illumina', annotate=True)

        process = self.latest_process()
        submissions = bio.submissions_to('assembly/illumina')
        self.assertEqual(len(submissions), 1)
        self.assertTrue(submissions[0]['annotate'])
        self.assertEqual(submissions[0]['files']['r1'], b'R1-CONTENT')
        self.assertEqual(submissions[0]['files']['r2'], b'R2-CONTENT')
        self.assertEqual(bio.submissions_to('annotation/upload'), [])

        self.assertTrue(all(task.status == TaskStatus.COMPLETED for task in self.process_tasks(process)))
        self.assertEqual(self.process_outputs(process, File.FileType.FASTA).count(), 1)
        json_outputs = self.process_outputs(process, File.FileType.JSON)
        self.assertEqual(json_outputs.count(), 1)
        self.assertEqual(FileGene.objects.filter(file=json_outputs.first()).count(), N_FEATURES)

    def test_complete_version_stores_sequences_and_positions(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True, complete=True)

        json_file = self.process_outputs(self.latest_process(), File.FileType.JSON).first()
        file_gene = FileGene.objects.filter(file=json_file).order_by('id').first()
        self.assertEqual(file_gene.start, BAKTA_JSON['features'][0]['start'])
        self.assertEqual(file_gene.nt, BAKTA_JSON['features'][0]['nt'])

    def test_without_complete_version_sequences_are_not_stored(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)

        json_file = self.process_outputs(self.latest_process(), File.FileType.JSON).first()
        self.assertFalse(FileGene.objects.filter(file=json_file, nt__isnull=False).exists())

    def test_auto_annotated_job_waits_for_annotation_to_finish(self):
        sequence = ['running', 'assembled', 'annotation_pending', 'running', 'annotated']
        with FakeBioService(status_sequence=sequence):
            self.run_assembly('ont', annotate=True)

        process = self.latest_process()
        json_outputs = self.process_outputs(process, File.FileType.JSON)
        self.assertEqual(json_outputs.count(), 1)
        self.assertEqual(FileGene.objects.filter(file=json_outputs.first()).count(), N_FEATURES)
        self.assertNotIn(TaskNotification.EVENT_WARNING, self.events(process))

    def test_invalid_assembly_requests_create_nothing(self):
        cases = [
            ('missing fastq', {'assembly_type': 'ont'}),
            ('unknown type', {'assembly_type': 'pacbio', 'fastq_file': fastq()}),
            ('illumina without R2', {'assembly_type': 'illumina', 'fastq_file': fastq()}),
            ('ont with R2', {'assembly_type': 'ont', 'fastq_file': fastq(), 'fastq_file_2': fastq('r2.fastq.gz')}),
        ]
        for label, data in cases:
            with self.subTest(label), FakeBioService() as bio:
                response = self.client.post(reverse('conversion:assembly_run'), data=data)
                self.assertRedirects(response, reverse('conversion:assembly_ui'), fetch_redirect_response=False)
                self.assertEqual(bio.submissions, [])
        self.assertFalse(ProcessGroup.objects.exists())


class AnnotationFlowTests(ConversionFlowMixin, TestCase):
    def test_annotation_of_uploaded_fasta_produces_genes(self):
        with FakeBioService() as bio:
            response = self.client.post(reverse('conversion:start_annotation_task'), data={'fasta_file': fasta()})

        process = self.latest_process()
        self.assertRedirects(response, reverse('conversion:process_status', args=[process.id]), fetch_redirect_response=False)
        submissions = bio.submissions_to('annotation/upload')
        self.assertEqual(len(submissions), 1)
        self.assertEqual(submissions[0]['files']['assembly'], b'>seq\nACGTACGT\n')

        self.assertTrue(all(task.status == TaskStatus.COMPLETED for task in self.process_tasks(process)))
        json_file = self.process_outputs(process, File.FileType.JSON).first()
        self.assertIsNotNone(json_file)
        self.assertEqual(FileGene.objects.filter(file=json_file).count(), N_FEATURES)

    def test_annotation_of_completed_assembly_stays_in_same_process(self):
        with FakeBioService() as bio:
            self.run_assembly('ont')
            process = self.latest_process()
            assembly_task = self.process_tasks(process).first()

            response = self.client.post(reverse('conversion:start_annotation_task'), data={'source_task_id': assembly_task.id})

        self.assertRedirects(response, reverse('conversion:process_status', args=[process.id]), fetch_redirect_response=False)
        self.assertEqual(ProcessGroup.objects.filter(user=self.user).count(), 1)
        self.assertEqual(bio.submissions_to('annotation/upload')[0]['files']['assembly'], ASSEMBLY_FASTA)
        json_file = self.process_outputs(process, File.FileType.JSON).first()
        self.assertEqual(FileGene.objects.filter(file=json_file).count(), N_FEATURES)

    def test_completed_assembly_is_offered_for_annotation_only_once(self):
        with FakeBioService():
            self.run_assembly('ont')
            assembly_task = self.process_tasks(self.latest_process()).first()

            page = self.client.get(reverse('conversion:annotation_ui'))
            self.assertIn(assembly_task.id, [task.id for task in page.context['available_fasta_jobs']])

            self.client.post(reverse('conversion:start_annotation_task'), data={'source_task_id': assembly_task.id})
            page = self.client.get(reverse('conversion:annotation_ui'))
            self.assertNotIn(assembly_task.id, [task.id for task in page.context['available_fasta_jobs']])

            n_tasks = ConversionTask.objects.count()
            self.client.post(reverse('conversion:start_annotation_task'), data={'source_task_id': assembly_task.id})
            self.assertEqual(ConversionTask.objects.count(), n_tasks)

    def test_auto_annotated_assembly_is_not_offered_for_annotation(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        page = self.client.get(reverse('conversion:annotation_ui'))
        self.assertEqual(list(page.context['available_fasta_jobs']), [])

    def test_cannot_annotate_assembly_of_other_user(self):
        with FakeBioService():
            self.run_assembly('ont')
            assembly_task = self.process_tasks(self.latest_process()).first()

            self.client.login(username='other-user', password='pass1234')
            n_tasks = ConversionTask.objects.count()
            self.client.post(reverse('conversion:start_annotation_task'), data={'source_task_id': assembly_task.id})
        self.assertEqual(ConversionTask.objects.count(), n_tasks)


class JsonFlowTests(ConversionFlowMixin, TestCase):
    def test_bakta_json_upload_links_genes_to_uploaded_file(self):
        with FakeBioService() as bio:
            response = self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})

        process = self.latest_process()
        self.assertRedirects(response, reverse('conversion:process_status', args=[process.id]), fetch_redirect_response=False)
        self.assertEqual(bio.submissions, [])
        self.assertTrue(all(task.status == TaskStatus.COMPLETED for task in self.process_tasks(process)))
        json_file = File.objects.get(user=self.user, file_type=File.FileType.JSON)
        self.assertEqual(FileGene.objects.filter(file=json_file).count(), N_FEATURES)
        self.assertIn(TaskNotification.EVENT_COMPLETED, self.events(process))

    def test_bakta_json_without_genes_completes_with_a_warning(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'),
                             data={'feature_file': bakta_json('empty.json', {'features': []})})

        process = self.latest_process()
        self.assertEqual({task.status for task in self.process_tasks(process)}, {TaskStatus.COMPLETED})
        self.assertIn(TaskNotification.EVENT_WARNING, self.events(process))
        self.assertIn(TaskNotification.EVENT_COMPLETED, self.events(process))
        response = self.client.get(reverse('conversion:process_status', args=[process.id]))
        self.assertTrue(response.context['extracted_without_genes'])
        self.assertContains(response, 'No genes found')

    def test_bakta_json_with_genes_does_not_warn(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})

        self.assertNotIn(TaskNotification.EVENT_WARNING, self.events(self.latest_process()))
        response = self.client.get(reverse('conversion:process_status', args=[self.latest_process().id]))
        self.assertFalse(response.context['extracted_without_genes'])
        self.assertNotContains(response, 'No genes found')

    def test_invalid_json_fails_and_notifies(self):
        bad = SimpleUploadedFile('bad.json', b'{not json', content_type='application/json')
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bad})

        process = self.latest_process()
        self.assertEqual({task.status for task in self.process_tasks(process)}, {TaskStatus.FAILED})
        self.assertIn(TaskNotification.EVENT_FAILED, self.events(process))

    def test_json_processing_only_accepts_post(self):
        response = self.client.get(reverse('conversion:annotation_from_json'))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(ProcessGroup.objects.exists())

    def test_unparseable_features_fail_but_keep_the_uploaded_file(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'),
                             data={'feature_file': bakta_json('broken.json', {'features': ['not a feature']})})

        process = self.latest_process()
        self.assertEqual({task.status for task in self.process_tasks(process)}, {TaskStatus.FAILED})
        self.assertIn(TaskNotification.EVENT_FAILED, self.events(process))
        uploaded = File.objects.get(user=self.user, file_type=File.FileType.JSON)
        with uploaded.file.open('rb') as f:
            self.assertEqual(json.loads(f.read()), {'features': ['not a feature']})
        self.assertFalse(FileGene.objects.exists())

    def test_unparseable_annotation_warns_and_keeps_bakta_json_downloadable(self):
        broken = {'features': ['not a feature']}
        with FakeBioService(annotation_payload=broken):
            self.client.post(reverse('conversion:start_annotation_task'), data={'fasta_file': fasta()})

        process = self.latest_process()
        self.assertIn(TaskNotification.EVENT_WARNING, self.events(process))
        self.assertFalse(FileGene.objects.exists())
        json_outputs = self.process_outputs(process, File.FileType.JSON)
        self.assertEqual(json_outputs.count(), 1)
        with json_outputs.first().file.open('rb') as f:
            self.assertEqual(json.loads(f.read()), broken)


    def test_annotation_without_genes_completes_with_a_warning(self):
        with FakeBioService(annotation_payload={'features': []}):
            self.client.post(reverse('conversion:start_annotation_task'), data={'fasta_file': fasta()})

        process = self.latest_process()
        self.assertEqual({task.status for task in self.process_tasks(process)}, {TaskStatus.COMPLETED})
        self.assertIn(TaskNotification.EVENT_WARNING, self.events(process))


class BioServiceProblemsTests(ConversionFlowMixin, TestCase):
    def test_busy_server_retries_and_then_warns_user(self):
        with FakeBioService(start_behavior='busy') as bio:
            self.run_assembly('ont')

        process = self.latest_process()
        self.assertGreater(len(bio.submissions_to('assembly/ont')), 1)
        self.assertFalse(self.process_tasks(process).filter(status=TaskStatus.COMPLETED).exists())
        self.assertIn(TaskNotification.EVENT_WARNING, self.events(process))

    def test_busy_server_for_annotation_retries_and_then_warns_user(self):
        with FakeBioService(start_behavior='busy') as bio:
            self.client.post(reverse('conversion:start_annotation_task'), data={'fasta_file': fasta()})

        process = self.latest_process()
        self.assertGreater(len(bio.submissions_to('annotation/upload')), 1)
        self.assertIn(TaskNotification.EVENT_WARNING, self.events(process))

    def test_failed_external_job_marks_task_failed_and_notifies(self):
        with FakeBioService(status_sequence=['running', 'failed']):
            self.run_assembly('ont')

        process = self.latest_process()
        self.assertIn(TaskStatus.FAILED, {task.status for task in self.process_tasks(process)})
        self.assertFalse(self.process_outputs(process, File.FileType.FASTA).exists())
        self.assertIn(TaskNotification.EVENT_FAILED, self.events(process))

    def test_missing_external_job_marks_task_failed_and_notifies(self):
        with FakeBioService(missing_jobs=True):
            self.run_assembly('ont')

        process = self.latest_process()
        self.assertIn(TaskStatus.FAILED, {task.status for task in self.process_tasks(process)})
        self.assertIn(TaskNotification.EVENT_FAILED, self.events(process))


class ProcessContractMixin(ConversionFlowMixin):
    """Helpers that only use what the UI exposes (rows, status context, download links)."""

    def status_context(self, process):
        response = self.client.get(reverse('conversion:process_status', args=[process.id]))
        self.assertEqual(response.status_code, 200)
        return response.context

    def row_for(self, process):
        rows = []
        page = 1
        while True:
            context = self.client.get(reverse('conversion:process_list'), {'page': page}).context
            rows.extend(context['page_obj'].object_list)
            if not context['page_obj'].has_next():
                break
            page += 1
        return next(row for row in rows if row['process_name'] == process.name)

    def retry(self, process):
        return self.client.post(reverse('conversion:retry_step', args=[process.id]))

    def annotate_assembly_of(self, process):
        return self.client.post(reverse('conversion:start_annotation_task'),
                                data={'source_task_id': self.status_context(process)['assembly_task_id']})

    def download(self, name, task_id):
        response = self.client.get(reverse(name, args=[task_id]))
        self.assertEqual(response.status_code, 200)
        return b''.join(response.streaming_content)


def steps(*pairs):
    return [{'label': label, 'state': state} for label, state in pairs]


class ProcessContractTests(ProcessContractMixin, TestCase):
    """Pins what the process list and status page show for each kind of process."""

    def assertRow(self, process, **expected):
        row = self.row_for(process)
        self.assertEqual({key: row.get(key) for key in expected}, expected)

    def assertStatus(self, process, timeline, **expected):
        context = self.status_context(process)
        self.assertEqual({key: context.get(key) for key in expected}, expected)
        self.assertEqual([(entry['label'], entry['status']) for entry in context['timeline']], timeline)
        return context

    def test_ont_assembly(self):
        with FakeBioService():
            self.run_assembly('ont')
        process = self.latest_process()
        self.assertRow(process, kind='assembly', pipeline_type='Assembly · ONT', status='completed',
                       top_pipeline='Assembly · ONT', can_annotate=True, can_retry_annotation=False,
                       has_fasta=True, has_json=False, is_auto_annotated=False, stage_class='process-stage-light',
                       steps=steps(('Started', 'complete'), ('Assembled', 'complete'), ('Annotated', 'pending')))
        self.assertEqual(self.row_for(process)['input_filename'], 'reads_R1.fastq.gz')
        context = self.assertStatus(process, [('Assembly · ONT', 'completed')], process_kind='assembly',
                                    pipeline_badges=['Assembly · ONT'], latest_task_status='completed',
                                    can_annotate=True, can_retry_annotation=False, json_download_task_id=None)
        self.assertEqual(self.download('conversion:download_fasta', context['fasta_download_task_id']), ASSEMBLY_FASTA)

    def test_ont_assembly_with_auto_annotation(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        process = self.latest_process()
        self.assertRow(process, kind='assembly', pipeline_type='Assembly + Annotation · ONT', status='completed',
                       top_pipeline='Assembly + Annotation · ONT', can_annotate=False, can_retry_annotation=False,
                       has_fasta=True, has_json=True, is_auto_annotated=True, stage_class='process-stage-max')
        self.assertEqual(self.row_for(process)['steps'][2], {'label': 'Annotated', 'state': 'complete'})
        context = self.assertStatus(process, [('Assembly + Annotation · ONT', 'completed')], process_kind='assembly',
                                    pipeline_badges=['Assembly + Annotation · ONT'], latest_task_status='completed',
                                    can_annotate=False, can_retry_annotation=False)
        self.assertEqual(self.download('conversion:download_fasta', context['fasta_download_task_id']), ASSEMBLY_FASTA)
        self.assertEqual(json.loads(self.download('conversion:download_json', context['json_download_task_id'])), BAKTA_JSON)

    def test_fasta_downloads_while_genes_of_auto_annotation_are_extracted(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        process = self.latest_process()
        self.process_tasks(process).filter(step='extract_bakta_json').update(status=TaskStatus.RUNNING)

        self.assertRow(process, status='running', has_fasta=True, has_json=False)
        context = self.assertStatus(process, [('Assembly + Annotation · ONT', 'running')], latest_task_status='running')
        self.assertEqual(self.download('conversion:download_fasta', context['fasta_download_task_id']), ASSEMBLY_FASTA)

    def test_completed_auto_annotation_shows_assembled_step_complete(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        self.assertEqual(self.row_for(self.latest_process())['steps'][1], {'label': 'Assembled', 'state': 'complete'})

    def test_illumina_assembly_then_manual_annotation(self):
        with FakeBioService():
            self.run_assembly('illumina')
            process = self.latest_process()
            self.annotate_assembly_of(process)
        self.assertRow(process, kind='assembly', pipeline_type='Assembly · Illumina', status='completed',
                       top_pipeline='Annotation', can_annotate=False, can_retry_annotation=False,
                       has_fasta=True, has_json=True, is_auto_annotated=False, stage_class='process-stage-max',
                       steps=steps(('Started', 'complete'), ('Assembled', 'complete'), ('Annotated', 'complete')))
        self.assertEqual(self.row_for(process)['input_filename'], 'reads_R1.fastq.gz, reads_R2.fastq.gz')
        context = self.assertStatus(process, [('Assembly · Illumina', 'completed'), ('Annotation', 'completed')],
                                    process_kind='assembly', pipeline_badges=['Assembly · Illumina', 'Annotation'],
                                    latest_task_status='completed', can_annotate=False, can_retry_annotation=False)
        self.assertEqual(self.download('conversion:download_fasta', context['fasta_download_task_id']), ASSEMBLY_FASTA)
        self.assertEqual(json.loads(self.download('conversion:download_json', context['json_download_task_id'])), BAKTA_JSON)

    def test_assembly_with_failed_annotation_offers_retry(self):
        with FakeBioService():
            self.run_assembly('ont')
        process = self.latest_process()
        with FakeBioService(status_sequence=['running', 'failed']):
            self.annotate_assembly_of(process)
        self.assertRow(process, status='failed', top_pipeline='Annotation', can_annotate=False,
                       can_retry_annotation=True, has_fasta=True, has_json=False, stage_class='process-stage-mid',
                       steps=steps(('Started', 'complete'), ('Assembled', 'complete'), ('Annotated', 'error')))
        self.assertStatus(process, [('Assembly · ONT', 'completed'), ('Annotation', 'failed')],
                          latest_task_status='failed', can_retry_annotation=True, json_download_task_id=None)

    def test_retry_button_retries_a_failed_annotation(self):
        with FakeBioService():
            self.run_assembly('ont')
        process = self.latest_process()
        with FakeBioService(status_sequence=['running', 'failed']):
            self.annotate_assembly_of(process)
        with FakeBioService() as bio:
            self.retry(process)
        self.assertEqual(len(bio.submissions_to('annotation/upload')), 1)
        self.assertRow(process, status='completed', has_json=True, can_retry_annotation=False)

    def test_retrying_failed_annotation_produces_genes(self):
        with FakeBioService():
            self.run_assembly('ont')
        process = self.latest_process()
        with FakeBioService(status_sequence=['running', 'failed']):
            self.annotate_assembly_of(process)
        with FakeBioService():
            self.annotate_assembly_of(process)
        self.assertRow(process, status='completed', has_json=True, can_retry_annotation=False)

    def test_failed_assembly_offers_retry_and_retrying_continues_the_plan(self):
        with FakeBioService(status_sequence=['running', 'failed']):
            self.run_assembly('ont', annotate=True)
        process = self.latest_process()
        self.assertStatus(process, [('Assembly + Annotation · ONT', 'failed')], can_retry_assembly=True)

        with FakeBioService() as bio:
            response = self.retry(process)

        self.assertRedirects(response, reverse('conversion:process_status', args=[process.id]), fetch_redirect_response=False)
        self.assertEqual(bio.submissions_to('assembly/ont')[0]['files']['reads'], b'R1-CONTENT')
        self.assertRow(process, status='completed', has_json=True)
        self.assertEqual(self.status_context(process)['can_retry_assembly'], False)

    def test_retry_is_only_for_failed_steps_of_the_user(self):
        with FakeBioService():
            self.run_assembly('ont')
        process = self.latest_process()
        self.assertEqual(self.status_context(process)['can_retry_assembly'], False)
        with FakeBioService() as bio:
            self.retry(process)
        self.assertEqual(bio.submissions_to('assembly/ont'), [])

        self.client.login(username='other-user', password='pass1234')
        self.assertEqual(self.retry(process).status_code, 404)

    def test_annotation_of_uploaded_fasta(self):
        with FakeBioService():
            self.client.post(reverse('conversion:start_annotation_task'), data={'fasta_file': fasta('up.fasta')})
        process = self.latest_process()
        self.assertRow(process, kind='annotation', pipeline_type='Annotation', status='completed',
                       can_annotate=False, can_retry_annotation=False, has_fasta=True, has_json=True,
                       stage_class='process-stage-max',
                       steps=steps(('Started', 'complete'), ('Annotating', 'complete'), ('Parsed', 'complete')))
        self.assertEqual(self.row_for(process)['input_filename'], 'up.fasta')
        context = self.assertStatus(process, [('Annotation', 'completed')], process_kind='annotation',
                                    pipeline_badges=['Annotation'], latest_task_status='completed', assembly_task_id=None)
        self.assertEqual(self.download('conversion:download_fasta', context['fasta_download_task_id']), b'>seq\nACGTACGT\n')
        self.assertEqual(json.loads(self.download('conversion:download_json', context['json_download_task_id'])), BAKTA_JSON)

    def test_uploaded_json(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json('up.json')})
        process = self.latest_process()
        self.assertRow(process, kind='json', pipeline_type='Gene extraction · Bakta JSON', status='completed', can_annotate=False,
                       can_retry_annotation=False, has_fasta=False, has_json=True, stage_class='process-stage-max',
                       steps=steps(('Started', 'complete'), ('Parsed', 'complete')))
        self.assertEqual(self.row_for(process)['input_filename'], 'up.json')
        context = self.assertStatus(process, [('Gene extraction · Bakta JSON', 'completed')], process_kind='json', pipeline_badges=['Gene extraction · Bakta JSON'],
                                    latest_task_status='completed', fasta_download_task_id=None, assembly_task_id=None)
        self.assertEqual(json.loads(self.download('conversion:download_json', context['json_download_task_id'])), BAKTA_JSON)
        self.assertContains(self.client.get(reverse('conversion:process_status', args=[process.id])),
                            reverse('conversion:download_json', args=[context['json_download_task_id']]))

    def test_process_shows_after_its_prediction_model_is_removed(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json('up.json')})
        process = self.latest_process()
        process.plan.append({'id': 'run1_removed_model', 'step': 'predict_removed_model', 'after': ['n1'],
                             'batch': 2, 'run': 1, 'parameters': {}})
        process.save(update_fields=['plan'])

        self.assertRow(process, kind='json', status='completed')
        self.assertStatus(process, [('Gene extraction · Bakta JSON', 'completed')], latest_task_status='completed')

    def test_pending_assembly_while_server_busy(self):
        with FakeBioService(start_behavior='busy'):
            self.run_assembly('ont')
        process = self.latest_process()
        self.assertRow(process, kind='assembly', status='pending', can_annotate=False, has_fasta=False,
                       has_json=False, stage_class='process-stage-light',
                       steps=steps(('Started', 'complete'), ('Assembled', 'current'), ('Annotated', 'pending')))
        context = self.assertStatus(process, [('Assembly · ONT', 'pending')], latest_task_status='pending',
                                    fasta_download_task_id=None, json_download_task_id=None)
        response = self.client.get(reverse('conversion:download_fasta', args=[context['assembly_task_id']]))
        self.assertRedirects(response, reverse('conversion:process_status', args=[process.id]), fetch_redirect_response=False)


class ProcessPagesTests(ProcessContractMixin, TestCase):
    def setUp(self):
        super().setUp()
        with FakeBioService():
            self.run_assembly('illumina', annotate=True)
            self.assembly_process = self.latest_process()
            self.client.post(reverse('conversion:start_annotation_task'), data={'fasta_file': fasta()})
            self.annotation_process = self.latest_process()
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
            self.json_process = self.latest_process()

    def test_pages_render(self):
        for name in ('conversion:assembly_ui', 'conversion:annotation_ui', 'conversion:process_list'):
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        for process in (self.assembly_process, self.annotation_process, self.json_process):
            with self.subTest(process.name):
                response = self.client.get(reverse('conversion:process_status', args=[process.id]))
                self.assertContains(response, process.name)

    def test_process_list_paginates_three_per_page(self):
        with FakeBioService():
            self.run_assembly('ont')
        first = self.client.get(reverse('conversion:process_list')).context['page_obj']
        self.assertEqual((first.paginator.count, len(first.object_list)), (4, 3))
        second = self.client.get(reverse('conversion:process_list'), {'page': 2}).context['page_obj']
        self.assertEqual(len(second.object_list), 1)

    def test_fastq_download_zips_both_reads(self):
        archive_bytes = self.download('conversion:download_fastq', self.status_context(self.assembly_process)['assembly_task_id'])
        with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
            self.assertEqual(sorted(archive.read(name) for name in archive.namelist()), [b'R1-CONTENT', b'R2-CONTENT'])

    def test_fastq_download_without_fastq_redirects(self):
        task_id = self.status_context(self.annotation_process)['fasta_download_task_id']
        response = self.client.get(reverse('conversion:download_fastq', args=[task_id]))
        self.assertRedirects(response, reverse('conversion:process_status', args=[self.annotation_process.id]), fetch_redirect_response=False)

    def test_json_download_of_uploaded_json_returns_original(self):
        task_id = self.row_for(self.json_process)['task'].id
        self.assertEqual(json.loads(self.download('conversion:download_json', task_id)), BAKTA_JSON)

    def test_fasta_download_without_fasta_redirects(self):
        task_id = self.row_for(self.json_process)['task'].id
        response = self.client.get(reverse('conversion:download_fasta', args=[task_id]))
        self.assertRedirects(response, reverse('conversion:process_status', args=[self.json_process.id]), fetch_redirect_response=False)

    def test_unknown_process_redirects_to_list(self):
        response = self.client.get(reverse('conversion:process_status', args=[999999]))
        self.assertRedirects(response, reverse('conversion:process_list'), fetch_redirect_response=False)

    def test_rename_process(self):
        url = reverse('conversion:rename_process', args=[self.assembly_process.id])
        response = self.client.post(url, data={'process_name': 'New name'})
        self.assertRedirects(response, reverse('conversion:process_status', args=[self.assembly_process.id]), fetch_redirect_response=False)
        self.assembly_process.refresh_from_db()
        self.assertEqual(self.assembly_process.name, 'New name')

        self.client.post(url, data={'process_name': '  '})
        self.assembly_process.refresh_from_db()
        self.assertEqual(self.assembly_process.name, 'New name')


class PermissionsTests(ProcessContractMixin, TestCase):
    def setUp(self):
        super().setUp()
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        self.process = self.latest_process()
        context = self.status_context(self.process)
        self.task_ids = {context['assembly_task_id'], context['fasta_download_task_id'], context['json_download_task_id']}
        self.client.login(username='other-user', password='pass1234')

    def test_other_user_cannot_see_process(self):
        response = self.client.get(reverse('conversion:process_status', args=[self.process.id]))
        self.assertRedirects(response, reverse('conversion:process_list'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('conversion:process_list')).context['page_obj'].paginator.count, 0)

    def test_other_user_cannot_download(self):
        for name in ('conversion:download_fastq', 'conversion:download_fasta', 'conversion:download_json'):
            for task_id in self.task_ids:
                with self.subTest(name=name, task_id=task_id):
                    self.assertEqual(self.client.get(reverse(name, args=[task_id])).status_code, 404)

    def test_other_user_cannot_rename(self):
        self.client.post(reverse('conversion:rename_process', args=[self.process.id]), data={'process_name': 'Hacked'})
        self.process.refresh_from_db()
        self.assertEqual(self.process.name, 'reads_R1.fastq.gz')

    def test_other_users_process_looks_exactly_like_a_missing_one(self):
        missing_id = ProcessGroup.objects.order_by('-id').first().id + 1000

        def status_page(process_id):
            response = self.client.get(reverse('conversion:process_status', args=[process_id]), follow=True)
            return response.redirect_chain, [str(m) for m in response.context['messages']]

        def rename(process_id):
            return self.client.post(reverse('conversion:rename_process', args=[process_id]), data={'process_name': 'x'}).status_code

        self.assertEqual(status_page(self.process.id), status_page(missing_id))
        self.assertEqual(rename(self.process.id), rename(missing_id))
        self.assertEqual(rename(self.process.id), 404)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        for url in (reverse('conversion:assembly_ui'), reverse('conversion:annotation_ui'),
                    reverse('conversion:process_list'), reverse('conversion:process_status', args=[self.process.id])):
            with self.subTest(url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('login', response['Location'])


TUBERCULOSIS = ('NCBITaxon:1773', 'Mycobacterium tuberculosis')


class OrganismTests(ConversionFlowMixin, TestCase):
    """New processes store the organism chosen among those the prediction models declare."""

    def setUp(self):
        super().setUp()
        self._organisms_backup = dict(MODEL_ORGANISMS)

    def tearDown(self):
        MODEL_ORGANISMS.clear()
        MODEL_ORGANISMS.update(self._organisms_backup)
        super().tearDown()

    def declare_tuberculosis_model(self):
        MODEL_ORGANISMS['fake_tb_model'] = dict([TUBERCULOSIS])

    def upload_pages(self):
        return [self.client.get(reverse(name)) for name in ('conversion:assembly_ui', 'conversion:annotation_ui')]

    def test_field_is_hidden_while_every_model_supports_any_organism(self):
        for page in self.upload_pages():
            self.assertNotContains(page, 'name="organism"')

        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
        self.assertEqual(self.latest_process().organism, '')

    def test_field_offers_the_organisms_declared_by_the_models(self):
        self.declare_tuberculosis_model()
        for page in self.upload_pages():
            self.assertContains(page, 'name="organism"')
            self.assertContains(page, f'<option value="{TUBERCULOSIS[0]}">{TUBERCULOSIS[1]}</option>', html=True)
            self.assertContains(page, '<option value="">Other / unknown</option>', html=True)

    def test_new_processes_store_the_chosen_organism(self):
        self.declare_tuberculosis_model()
        uploads = [
            ('assembly', 'conversion:assembly_run', {'assembly_type': 'ont', 'fastq_file': fastq()}),
            ('fasta', 'conversion:start_annotation_task', {'fasta_file': fasta()}),
            ('json', 'conversion:annotation_from_json', {'feature_file': bakta_json()}),
        ]
        for label, url, data in uploads:
            with self.subTest(label), FakeBioService():
                self.client.post(reverse(url), data={**data, 'organism': TUBERCULOSIS[0]})
                self.assertEqual(self.latest_process().organism, TUBERCULOSIS[0])

    def upload_json(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
        return self.latest_process()

    def test_the_organism_of_a_sample_can_be_set_and_changed_later(self):
        process = self.upload_json()
        page = reverse('conversion:process_status', args=[process.id])
        self.assertNotContains(self.client.get(page), 'id="organism"')

        self.declare_tuberculosis_model()
        self.assertContains(self.client.get(page), 'id="organism"')
        set_organism = reverse('conversion:set_organism', args=[process.id])
        self.client.post(set_organism, data={'organism': TUBERCULOSIS[0]})
        process.refresh_from_db()
        self.assertEqual(process.organism, TUBERCULOSIS[0])

        self.client.post(set_organism, data={'organism': 'NCBITaxon:562'})  # not offered by any model
        process.refresh_from_db()
        self.assertEqual(process.organism, TUBERCULOSIS[0])

        self.client.post(set_organism, data={'organism': ''})
        process.refresh_from_db()
        self.assertEqual(process.organism, '')

    def test_other_users_cannot_set_the_organism(self):
        process = self.upload_json()
        self.declare_tuberculosis_model()
        self.client.login(username='other-user', password='pass1234')

        response = self.client.post(reverse('conversion:set_organism', args=[process.id]), data={'organism': TUBERCULOSIS[0]})

        self.assertEqual(response.status_code, 404)

    def test_unknown_organism_is_rejected(self):
        self.declare_tuberculosis_model()
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'),
                             data={'feature_file': bakta_json(), 'organism': 'NCBITaxon:562'})
        self.assertFalse(ProcessGroup.objects.exists())
        self.assertFalse(File.objects.exists())


class ProcessFileDownloadTests(ConversionFlowMixin, TestCase):
    """Each file of a process can be downloaded on its own (the RDF description links to it)."""

    def setUp(self):
        super().setUp()
        with FakeBioService():
            self.run_assembly('illumina')
        self.process = self.latest_process()
        assembly = self.process_tasks(self.process).first()
        self.r1, self.r2 = assembly.input_file('r1'), assembly.input_file('r2')

    def download(self, process, file):
        return self.client.get(reverse('conversion:process_file', args=[process.id, file.id]))

    def test_each_file_downloads_exactly_its_content(self):
        for file, content in ((self.r1, b'R1-CONTENT'), (self.r2, b'R2-CONTENT')):
            with self.subTest(file=file.id):
                response = self.download(self.process, file)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b''.join(response.streaming_content), content)

    def test_files_of_other_processes_are_not_found(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
        other_process = self.latest_process()

        self.assertEqual(self.download(other_process, self.r1).status_code, 404)

    def test_other_users_cannot_download(self):
        self.client.login(username='other-user', password='pass1234')

        self.assertEqual(self.download(self.process, self.r1).status_code, 404)


class SoftwareRecordTests(ConversionFlowMixin, TestCase):
    """Each finished task keeps the software it used, and each stored file its SHA-256."""

    def test_stored_files_keep_the_sha256_of_their_content(self):
        with FakeBioService():
            self.run_assembly('ont', files=[fastq('reads.fastq.gz', b'R1-CONTENT')])

        process = self.latest_process()
        reads = File.objects.get(consumed_by_tasks__process=process, file_type=File.FileType.FASTQ)
        assembly = self.process_outputs(process, File.FileType.FASTA).get()
        self.assertEqual(reads.sha256, hashlib.sha256(b'R1-CONTENT').hexdigest())
        self.assertEqual(assembly.sha256, hashlib.sha256(ASSEMBLY_FASTA).hexdigest())
