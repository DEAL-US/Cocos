from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from conversion.models import ConversionTask
from core.models import ProcessGroup
from notifications.models import TaskNotification
from prediction.models import PredictionRun, PredictionTask
from notifications.services import (
    _send_email_notification,
    notify_user_conversion_complete,
    notify_user_conversion_failed,
    notify_user_conversion_started,
    notify_user_server_busy,
)


User = get_user_model()


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user', password='pass1234', email='user@example.com')
        self.process = ProcessGroup.objects.create(name='process-1', user=self.user)
        self.task = ConversionTask.objects.create(
            external_job_id='job-1',
            status='running',
            step='bakta_annotation',
            process=self.process,
        )

    def test_notification_persist_events(self):
        scenarios = [
            (
                'started',
                lambda: notify_user_conversion_started(self.user, self.task),
                TaskNotification.EVENT_STARTED,
                'The Annotation for the process process-1 has started and is now running.',
            ),
            (
                'complete',
                lambda: notify_user_conversion_complete(self.user, self.task),
                TaskNotification.EVENT_COMPLETED,
                'The Annotation for the process process-1 is complete. You can now access your results.',
            ),
            (
                'failed-custom',
                lambda: notify_user_conversion_failed(self.user, self.task, message='custom failure'),
                TaskNotification.EVENT_FAILED,
                'custom failure',
            ),
            (
                'failed-default',
                lambda: notify_user_conversion_failed(self.user, self.task),
                TaskNotification.EVENT_FAILED,
                'The Annotation for the process process-1 has failed. Please try again.',
            ),
            (
                'server-busy',
                lambda: notify_user_server_busy(self.user, self.task),
                TaskNotification.EVENT_WARNING,
                'The bio service server is currently at maximum capacity. Please try again later.',
            ),
        ]

        for label, call_function, expected_event, expected_message in scenarios:
            with self.subTest(label=label):
                TaskNotification.objects.all().delete()
                with patch('notifications.services._send_email_notification', return_value=False) as email_mock:
                    notification = call_function()

                self.assertIsNotNone(notification)
                self.assertEqual(notification.user_id, self.user.id)
                self.assertEqual(notification.task_id, self.task.id)
                self.assertEqual(notification.event_type, expected_event)
                self.assertEqual(notification.message, expected_message)
                self.assertEqual(notification.channels, [TaskNotification.CHANNEL_IN_APP])
                self.assertFalse(notification.is_read)
                email_mock.assert_called_once_with(self.user, expected_message)


    @patch('notifications.services._send_email_notification', return_value=True)
    def test_notification_adds_email_channel_when_send_succeeds(self, email_mock):
        notification = notify_user_server_busy(self.user, self.task)

        self.assertEqual(
            notification.channels,
            [TaskNotification.CHANNEL_IN_APP, TaskNotification.CHANNEL_EMAIL],
        )
        email_mock.assert_called_once_with(self.user, 'The bio service server is currently at maximum capacity. Please try again later.')

    @patch('notifications.services._send_email_notification')
    def test_notify_returns_none_without_user(self, email_mock):
        TaskNotification.objects.all().delete()
        notification = notify_user_server_busy(None, self.task)

        self.assertIsNone(notification)
        self.assertFalse(TaskNotification.objects.exists())
        email_mock.assert_not_called()

    @patch('notifications.services._send_email_notification')
    def test_notify_returns_none_without_task(self, email_mock):
        TaskNotification.objects.all().delete()
        notification = notify_user_server_busy(self.user, None)

        self.assertIsNone(notification)
        self.assertFalse(TaskNotification.objects.exists())
        email_mock.assert_not_called()

    @override_settings(DEFAULT_FROM_EMAIL='noreply@example.com')
    @patch('notifications.services.send_mail')
    def test_send_email_notification_success_and_error_paths(self, send_mail_mock):
        cases = [
            ('success', None, True),
            ('error', Exception('smtp error'), False),
        ]

        for label, side_effect, expected_result in cases:
            with self.subTest(label=label):
                send_mail_mock.reset_mock()
                send_mail_mock.side_effect = side_effect
                send_mail_mock.return_value = 1

                was_sent = _send_email_notification(self.user, 'hello')
                self.assertEqual(was_sent, expected_result)

                send_mail_mock.assert_called_once()
                _, kwargs = send_mail_mock.call_args
                self.assertEqual(kwargs['message'], 'hello')
                self.assertEqual(kwargs['from_email'], 'noreply@example.com')
                self.assertEqual(kwargs['recipient_list'], [self.user.email])
                self.assertFalse(kwargs['fail_silently'])

    @override_settings(DEFAULT_FROM_EMAIL='')
    @patch('notifications.services.send_mail')
    def test_no_email_sent_when_no_email_or_no_user(self, send_mail_mock):
        cases = [
            ('missing-from-email', self.user, 'hello'),
            ('missing-user', None, 'hello'),
        ]

        for label, user, message in cases:
            with self.subTest(label=label):
                send_mail_mock.reset_mock()
                was_sent = _send_email_notification(user, message)
                self.assertFalse(was_sent)
                send_mail_mock.assert_not_called()


class TaskNotificationTaskTypesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user', password='pass1234', email='user@example.com')
        self.process = ProcessGroup.objects.create(name='process-1', user=self.user)

    @patch('notifications.services._send_email_notification', return_value=False)
    def test_notifications_link_to_any_task_type(self, email_mock):
        conversion = ConversionTask.objects.create(process=self.process, step='extract_bakta_json')
        run = PredictionRun.objects.create(process=self.process, selected_models=['base_bakta_50'], selected_antibiotics=['amikacin'])
        prediction = PredictionTask.objects.create(process=self.process, step='predict_base_bakta_50', run=run)

        for task in (conversion, prediction):
            with self.subTest(task=type(task).__name__):
                notification = notify_user_conversion_started(self.user, task, message='started')

                self.assertEqual(notification.task_id, task.pk)
                self.assertEqual(notification.task.concrete, task)
                self.assertIsInstance(notification.task.concrete, type(task))
                self.assertTrue(TaskNotification.objects.filter(task=task).exists())
