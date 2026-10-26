"""Conversion steps run on their own, against the fake bio service."""
import json

from django.core.files.base import ContentFile
from django.test import TestCase

from core.models import File, FileGene, ProcessGroup, Task
from core.steps import Busy, Started, StepError, get_step
from core.testing import ASSEMBLY_FASTA, BAKTA_JSON, FakeBioService, FlowTestMixin


class StepExecutionTestCase(FlowTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.process = ProcessGroup.objects.create(name='sample', user=self.user)

    def make_file(self, file_type, content, name):
        file = File(user=self.user, file_type=file_type)
        file.file.save(name, ContentFile(content), save=True)
        return file

    def make_task(self, step_key, inputs=None, parameters=None):
        step = get_step(step_key)
        task = Task.objects.create(process=self.process, step=step_key, parameters=step.build_parameters(parameters))
        for role, file in (inputs or {}).items():
            task.add_input(role, file)
        return task

    def reads(self, content=b'READS', name='reads.fastq.gz'):
        return self.make_file(File.FileType.FASTQ, content, name)

    def submit(self, bio, task):
        """Run process() and, if the job was accepted, store its id as the orchestrator will."""
        result = task.get_step().process(task)
        if isinstance(result, Started):
            task.external_job_id = result.job_id
            task.save(update_fields=['external_job_id'])
        return result

    def finish_job(self, bio, task, status):
        bio.jobs[task.external_job_id]['status'] = status


class AssemblyStepTests(StepExecutionTestCase):
    def test_ont_submits_reads_and_collects_the_assembly(self):
        task = self.make_task('assembly_ont', {'reads': self.reads(b'ONT-READS')})
        with FakeBioService() as bio:
            self.assertIsInstance(self.submit(bio, task), Started)
            [submission] = bio.submissions_to('assembly/ont')
            self.assertEqual((submission['annotate'], submission['files']['reads']), (False, b'ONT-READS'))

            self.finish_job(bio, task, 'assembled')
            task.get_step().collect(task)

        with task.output_file('assembly').file.open('rb') as f:
            self.assertEqual(f.read(), ASSEMBLY_FASTA)
        self.assertFalse(task.task_outputs.filter(role='annotation').exists())

    def test_illumina_with_annotation_sends_both_reads_and_collects_both_outputs(self):
        task = self.make_task('assembly_illumina_annotated', {'r1': self.reads(b'R1', 'r1.fastq.gz'),
                                                              'r2': self.reads(b'R2', 'r2.fastq.gz')})
        with FakeBioService() as bio:
            self.submit(bio, task)
            [submission] = bio.submissions_to('assembly/illumina')
            self.assertTrue(submission['annotate'])
            self.assertEqual((submission['files']['r1'], submission['files']['r2']), (b'R1', b'R2'))

            self.finish_job(bio, task, 'annotated')
            task.get_step().collect(task)

        self.assertEqual(task.output_file('assembly').file_type, File.FileType.FASTA)
        with task.output_file('annotation').file.open('rb') as f:
            self.assertEqual(json.load(f), BAKTA_JSON)

    def test_busy_service(self):
        task = self.make_task('assembly_ont', {'reads': self.reads()})
        with FakeBioService(start_behavior='busy'):
            self.assertEqual(self.submit(None, task), Busy())
        self.assertIsNone(task.external_job_id)

    def test_collect_can_be_retried_after_a_partial_failure(self):
        task = self.make_task('assembly_ont_annotated', {'reads': self.reads()})
        with FakeBioService() as bio:
            self.submit(bio, task)
            self.finish_job(bio, task, 'annotated')
            step = task.get_step()
            step.save_assembly(task)  # as if the annotation download had failed afterwards
            step.collect(task)

        self.assertEqual(task.task_outputs.filter(role='assembly').count(), 1)
        self.assertEqual(task.task_outputs.filter(role='annotation').count(), 1)

    def test_job_status_comes_from_the_service(self):
        task = self.make_task('assembly_ont', {'reads': self.reads()})
        with FakeBioService(status_sequence=['running', 'assembled']) as bio:
            self.submit(bio, task)
            step = task.get_step()
            self.assertEqual(step.job_status(task.external_job_id), ('running', 200))
            self.assertEqual(step.job_status(task.external_job_id), ('assembled', 200))
        with FakeBioService(missing_jobs=True):
            self.assertEqual(step.job_status('job-404'), (None, 404))


class AnnotationStepTests(StepExecutionTestCase):
    def assembly(self):
        return self.make_file(File.FileType.FASTA, b'>contig\nACGT\n', 'contigs.fasta')

    def test_uploads_the_assembly_with_threads_and_collects_the_annotation(self):
        task = self.make_task('bakta_annotation', {'assembly': self.assembly()}, {'threads': 8})
        with FakeBioService() as bio:
            self.assertIsInstance(self.submit(bio, task), Started)
            [submission] = bio.submissions_to('annotation/upload')
            self.assertEqual(submission['files']['assembly'], b'>contig\nACGT\n')
            self.assertEqual(submission['threads'], '8')

            self.finish_job(bio, task, 'annotated')
            task.get_step().collect(task)

        with task.output_file('annotation').file.open('rb') as f:
            self.assertEqual(json.load(f), BAKTA_JSON)

    def test_feature_lists_are_wrapped_in_a_features_object(self):
        task = self.make_task('bakta_annotation', {'assembly': self.assembly()})
        with FakeBioService(annotation_payload=BAKTA_JSON['features']) as bio:
            self.submit(bio, task)
            self.finish_job(bio, task, 'annotated')
            task.get_step().collect(task)

        with task.output_file('annotation').file.open('rb') as f:
            self.assertEqual(json.load(f), {'features': BAKTA_JSON['features']})


class GeneExtractionStepTests(StepExecutionTestCase):
    def annotation(self, payload=None, raw=None):
        content = raw if raw is not None else json.dumps(BAKTA_JSON if payload is None else payload).encode()
        return self.make_file(File.FileType.JSON, content, 'annotation.json')

    def test_links_the_genes_to_the_annotation_file(self):
        annotation = self.annotation()
        task = self.make_task('extract_bakta_json', {'annotation': annotation})

        task.get_step().process(task)

        self.assertEqual(task.output_file('genes'), annotation)
        self.assertEqual(FileGene.objects.filter(file=annotation).count(), len(BAKTA_JSON['features']))
        self.assertFalse(FileGene.objects.filter(file=annotation, nt__isnull=False).exists())

    def test_complete_version_stores_sequences(self):
        annotation = self.annotation()
        task = self.make_task('extract_bakta_json', {'annotation': annotation}, {'complete_version': True})

        task.get_step().process(task)

        first = FileGene.objects.filter(file=annotation).order_by('id').first()
        self.assertEqual(first.nt, BAKTA_JSON['features'][0]['nt'])

    def test_failures_raise_a_step_error_and_keep_the_file(self):
        cases = [
            ('invalid json', {'raw': b'{not json'}, 'Error decoding JSON file.'),
            ('unparseable features', {'payload': {'features': ['not a feature']}}, 'Error parsing features.'),
        ]
        for label, kwargs, message in cases:
            with self.subTest(label):
                annotation = self.annotation(**kwargs)
                task = self.make_task('extract_bakta_json', {'annotation': annotation})
                with self.assertRaisesMessage(StepError, message):
                    task.get_step().process(task)
                self.assertTrue(File.objects.filter(pk=annotation.pk).exists())
                self.assertFalse(FileGene.objects.filter(file=annotation).exists())
                self.assertFalse(task.task_outputs.exists())
