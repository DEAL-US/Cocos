import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from conversion.models import ConversionTask
from core.models import File, ProcessGroup, Task

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
        conversion = ConversionTask.objects.create(process=self.process, task_type='annotation', external_job_id='job-1')
        self.assertEqual(Task.objects.get(pk=conversion.pk).external_job_id, 'job-1')
        self.assertEqual(ConversionTask.objects.get(external_job_id='job-1'), conversion)
        with self.assertRaises(ValidationError):
            Task(process=self.process, external_job_id='job-1').full_clean()

    def test_tasks_without_external_job(self):
        self.assertIsNone(self.make_task().external_job_id)
        self.make_task()
