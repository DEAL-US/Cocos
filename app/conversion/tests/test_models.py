from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from conversion.models import ConversionTask
from core.models import ProcessGroup

User = get_user_model()


class ConversionTaskModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user", password="pass1234")
        self.process = ProcessGroup.objects.create(name="process", user=self.user)

    def test_external_job_id_required_once_task_is_running(self):
        cases = [
            ("pending", None, False),
            ("pending", "job-0", False),
            ("failed", None, False),
            ("running", None, True),
            ("running", "job-1", False),
            ("completed", None, True),
            ("completed", "job-2", False),
        ]
        for status, job_id, should_raise in cases:
            with self.subTest(status=status, job_id=job_id):
                task = ConversionTask(external_job_id=job_id, status=status, step="bakta_annotation", process=self.process)
                if should_raise:
                    with self.assertRaises(ValidationError):
                        task.save()
                else:
                    task.save()
                    self.assertEqual(task.status, status)

    def test_local_tasks_do_not_need_external_job_id(self):
        task = ConversionTask(status="completed", step="extract_bakta_json", process=self.process)
        task.save()
        self.assertIsNone(task.external_job_id)
