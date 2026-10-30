"""run_step and poll_step on single tasks, with Celery running eagerly and the fake bio service."""
import json

from django.core.files.base import ContentFile
from django.test import TestCase

from conversion.models import ConversionTask
from core.models import File, FileGene, ProcessGroup, TaskStatus
from core.steps import get_step
from core.tasks import run_step
from core.testing import ASSEMBLY_FASTA, BAKTA_JSON, FakeBioService, FlowTestMixin
from notifications.models import TaskNotification


class StepTasksTests(FlowTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.process = ProcessGroup.objects.create(name='sample.fastq.gz', user=self.user)

    def make_file(self, file_type, content, name):
        file = File(user=self.user, file_type=file_type)
        file.file.save(name, ContentFile(content), save=True)
        return file

    def make_task(self, step_key, inputs, parameters=None):
        step = get_step(step_key)
        task = ConversionTask.objects.create(process=self.process, step=step_key,
                                             parameters=step.build_parameters(parameters))
        for role, file in inputs.items():
            task.add_input(role, file)
        return task

    def ont_task(self, step_key='assembly_ont'):
        return self.make_task(step_key, {'reads': self.make_file(File.FileType.FASTQ, b'READS', 'reads.fastq.gz')})

    def run_task(self, task):
        run_step.delay(task.id)
        task.refresh_from_db()
        return task

    def events(self, task):
        return list(TaskNotification.objects.filter(task=task).order_by('id').values_list('event_type', 'message'))

    def test_external_step_runs_until_its_job_finishes(self):
        with FakeBioService(status_sequence=['running', 'assembled', 'annotation_pending', 'annotated']):
            task = self.run_task(self.ont_task('assembly_ont_annotated'))

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertTrue(task.external_job_id)
        self.assertIsNotNone(task.started_at)
        self.assertGreaterEqual(task.finished_at, task.started_at)
        with task.output_file('assembly').file.open('rb') as f:
            self.assertEqual(f.read(), ASSEMBLY_FASTA)
        self.assertEqual(task.output_file('annotation').file_type, File.FileType.JSON)
        self.assertEqual(self.events(task), [
            (TaskNotification.EVENT_STARTED, 'The Assembly + Annotation · ONT for the sample sample.fastq.gz has started and is now running.'),
            (TaskNotification.EVENT_COMPLETED, 'The Assembly + Annotation · ONT for the sample sample.fastq.gz is complete. You can now access your results.'),
        ])

    def test_local_step_runs_at_once(self):
        annotation = self.make_file(File.FileType.JSON, json.dumps(BAKTA_JSON).encode(), 'annotation.json')
        task = self.run_task(self.make_task('extract_bakta_json', {'annotation': annotation}))

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNone(task.external_job_id)
        self.assertIsNotNone(task.finished_at)
        self.assertEqual(FileGene.objects.filter(file=annotation).count(), len(BAKTA_JSON['features']))

    def test_local_step_failure_is_reported_with_its_message(self):
        annotation = self.make_file(File.FileType.JSON, b'{not json', 'annotation.json')
        task = self.run_task(self.make_task('extract_bakta_json', {'annotation': annotation}))

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn((TaskNotification.EVENT_FAILED, 'Error decoding JSON file.'), self.events(task))

    def test_busy_service_retries_and_then_warns(self):
        with FakeBioService(start_behavior='busy') as bio:
            task = self.run_task(self.ont_task())

        self.assertGreater(len(bio.submissions_to('assembly/ont')), 1)
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertEqual([event for event, _ in self.events(task)], [TaskNotification.EVENT_WARNING])

    def test_failed_and_missing_jobs_fail_the_task(self):
        cases = [
            ('failed job', {'status_sequence': ['running', 'failed']}, 'External job failed'),
            ('missing job', {'missing_jobs': True}, 'External job not found'),
        ]
        for label, fake_options, message in cases:
            with self.subTest(label), FakeBioService(**fake_options):
                task = self.run_task(self.ont_task())
                self.assertEqual(task.status, TaskStatus.FAILED)
                self.assertIn((TaskNotification.EVENT_FAILED, message), self.events(task))
                self.assertFalse(task.task_outputs.exists())

    def test_results_that_cannot_be_collected_fail_after_retries(self):
        with FakeBioService(annotation_payload='not a bakta json'):
            task = self.run_task(self.ont_task('assembly_ont_annotated'))

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn((TaskNotification.EVENT_FAILED, 'Max retries exceeded while collecting results'), self.events(task))

    def test_only_pending_tasks_are_started(self):
        task = self.ont_task()
        task.status = TaskStatus.FAILED
        task.save()
        with FakeBioService() as bio:
            self.run_task(task)
        self.assertEqual(bio.submissions, [])
