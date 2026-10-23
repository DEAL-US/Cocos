import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from conversion.models import ConversionTask
from core.models import File, ProcessGroup, Task, TaskInput, TaskOutput
from prediction.models import PredictionRun, PredictionTask

User = get_user_model()


class TaskModelTestCase(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        media_override = override_settings(MEDIA_ROOT=self.media_dir)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)

        self.user = User.objects.create_user(username='user', password='pass1234')
        self.process = ProcessGroup.objects.create(name='sample', user=self.user)

    def make_file(self, file_type, content=b'content', name='file'):
        file = File(user=self.user, file_type=file_type)
        file.file.save(f'{name}.{file_type}', ContentFile(content), save=True)
        return file

    def make_task(self, step='', **fields):
        if step:
            fields['step'] = step
        return Task.objects.create(process=self.process, **fields)


class TaskExternalJobTests(TaskModelTestCase):
    def test_external_job_id_lives_on_task_and_is_inherited(self):
        conversion = ConversionTask.objects.create(process=self.process, step='bakta_annotation', external_job_id='job-1')
        self.assertEqual(Task.objects.get(pk=conversion.pk).external_job_id, 'job-1')
        self.assertEqual(ConversionTask.objects.get(external_job_id='job-1'), conversion)
        with self.assertRaises(ValidationError):
            Task(process=self.process, external_job_id='job-1').full_clean()

    def test_tasks_without_external_job(self):
        self.assertIsNone(self.make_task().external_job_id)
        self.make_task()


class TaskStepTests(TaskModelTestCase):
    def test_step_must_be_registered(self):
        cases = [('', True), ('assembly_ont', False), ('extract_bakta_json', False), ('no_such_step', True)]
        for step, should_fail in cases:
            with self.subTest(step=step):
                task = Task(process=self.process, step=step)
                if should_fail:
                    with self.assertRaises(ValidationError):
                        task.full_clean()
                else:
                    task.full_clean()

    def test_subclasses_also_validate_the_step(self):
        with self.assertRaises(ValidationError):
            ConversionTask.objects.create(process=self.process, step='no_such_step')

    def test_get_step_returns_the_registered_step(self):
        self.assertEqual(self.make_task('bakta_annotation').get_step().key, 'bakta_annotation')

    def test_new_fields_have_safe_defaults(self):
        task = self.make_task('assembly_ont')
        task.refresh_from_db()
        self.assertEqual((task.parameters, task.plan_node, task.software), ({}, '', []))
        self.assertIsNone(task.started_at)
        self.assertIsNone(task.finished_at)


class TaskFilesTests(TaskModelTestCase):
    def test_inputs_and_outputs_by_role(self):
        task = self.make_task('assembly_illumina')
        r1 = self.make_file(File.FileType.FASTQ, b'R1', 'r1')
        r2 = self.make_file(File.FileType.FASTQ, b'R2', 'r2')
        task.add_input('r1', r1)
        task.add_input('r2', r2)

        self.assertEqual(task.input_file('r2'), r2)
        self.assertEqual(task.read_input('r1'), b'R1')
        self.assertEqual(set(task.inputs.all()), {r1, r2})
        self.assertEqual(list(r1.consumed_by_tasks.all()), [task])

        assembly = task.save_output('assembly', b'>contig\nACGT\n', File.FileType.FASTA, 'contigs.fasta')
        self.assertEqual((assembly.user, assembly.file_type), (self.user, File.FileType.FASTA))
        self.assertEqual(task.output_file('assembly'), assembly)
        self.assertEqual(list(assembly.produced_by_tasks.all()), [task])
        with assembly.file.open('rb') as f:
            self.assertEqual(f.read(), b'>contig\nACGT\n')

    def test_missing_role_raises(self):
        task = self.make_task('assembly_ont')
        with self.assertRaises(ObjectDoesNotExist):
            task.input_file('reads')
        with self.assertRaises(ObjectDoesNotExist):
            task.output_file('assembly')

    def test_one_file_per_role(self):
        task = self.make_task('assembly_ont')
        task.add_input('reads', self.make_file(File.FileType.FASTQ, name='a'))
        with self.assertRaises(ValidationError):
            task.add_input('reads', self.make_file(File.FileType.FASTQ, name='b'))
        self.assertEqual(TaskInput.objects.filter(task=task).count(), 1)

    def test_role_must_be_declared_by_the_step(self):
        task = self.make_task('assembly_ont')
        cases = [
            (lambda: task.add_input('r1', self.make_file(File.FileType.FASTQ)), 'unknown input role'),
            (lambda: task.add_output('annotation', self.make_file(File.FileType.JSON)), 'output only of annotated assembly'),
        ]
        for action, label in cases:
            with self.subTest(label):
                with self.assertRaises(ValidationError):
                    action()

    def test_file_format_must_match_the_port(self):
        task = self.make_task('bakta_annotation')
        with self.assertRaises(ValidationError):
            task.add_input('assembly', self.make_file(File.FileType.FASTQ))
        task.add_input('assembly', self.make_file(File.FileType.FASTA))

    def test_tasks_without_step_accept_any_role(self):
        task = self.make_task()
        task.add_input('anything', self.make_file(File.FileType.CSV))
        task.add_output('whatever', self.make_file(File.FileType.JSON))
        self.assertEqual(TaskOutput.objects.filter(task=task).count(), 1)

    def test_deleting_a_file_removes_its_links(self):
        task = self.make_task('assembly_ont')
        reads = self.make_file(File.FileType.FASTQ)
        task.add_input('reads', reads)
        reads.delete()
        self.assertFalse(TaskInput.objects.filter(task=task).exists())


class ProcessGroupTests(TaskModelTestCase):
    def test_organism_is_blank_or_an_ncbi_taxon_curie(self):
        cases = [('', True), ('NCBITaxon:562', True), ('NCBITaxon:1773', True),
                 ('562', False), ('Escherichia coli', False), ('NCBITaxon:abc', False)]
        for organism, valid in cases:
            with self.subTest(organism=organism):
                process = ProcessGroup(name='p', user=self.user, organism=organism)
                if valid:
                    process.full_clean()
                else:
                    with self.assertRaises(ValidationError):
                        process.full_clean()

    def test_defaults(self):
        self.process.refresh_from_db()
        self.assertEqual((self.process.organism, self.process.plan), ('', []))


class PredictionRunTests(TaskModelTestCase):
    def test_run_groups_one_task_per_model(self):
        run = PredictionRun.objects.create(process=self.process, selected_models=['a', 'b'], selected_antibiotics=['amikacin'])
        for _ in ('a', 'b'):
            PredictionTask.objects.create(process=self.process, step='predict_base_bakta_50', run=run, results={'amikacin': 0.5})

        self.assertEqual(run.status, 'pending')
        self.assertEqual(run.tasks.count(), 2)
        self.assertEqual([task.results for task in run.tasks.all()], [{'amikacin': 0.5}] * 2)
        self.assertEqual(list(self.process.prediction_runs.all()), [run])

    def test_run_needs_models_and_antibiotics(self):
        with self.assertRaises(ValidationError):
            PredictionRun.objects.create(process=self.process)

    def test_output_csv_must_be_a_csv(self):
        run = PredictionRun(process=self.process, selected_models=['a'], selected_antibiotics=['amikacin'],
                            output_csv=self.make_file(File.FileType.JSON))
        with self.assertRaises(ValidationError):
            run.save()
        run.output_csv = self.make_file(File.FileType.CSV)
        run.save()
