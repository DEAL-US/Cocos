import logging

from django.conf import settings
from django.core.mail import send_mail

from notifications.models import TaskNotification, UserNotificationSettings

logger = logging.getLogger(__name__)

EMAIL_SUBJECT = getattr(settings, 'NOTIFICATION_EMAIL_SUBJECT', 'Cocos Process Notification')


def _send_email_notification(user, message):
    if not user or not user.email:
        return False

    settings_obj = UserNotificationSettings.objects.filter(user=user).only('email_notifications_enabled').first()
    if settings_obj is not None and not settings_obj.email_notifications_enabled:
        return False

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
    if not from_email:
        logger.warning('DEFAULT_FROM_EMAIL is not configured; skipping notification email for user=%s', user.id)
        return False

    try:
        send_mail(
            subject=EMAIL_SUBJECT,
            message=message,
            from_email=from_email,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception('Failed to send notification email for user=%s', user.id)
        return False

def _create_notification(user, event_type, message, task=None):
    if not user or not user.is_authenticated or not task:
        logger.warning(
            'Skipping notification without user or task. event_type=%s task_id=%s',
            event_type,
            getattr(task, 'id', None),
        )
        return None
    channels = [TaskNotification.CHANNEL_IN_APP]
    if _send_email_notification(user, message):
        channels.append(TaskNotification.CHANNEL_EMAIL)

    return TaskNotification.objects.create(
        user=user,
        task=task,
        event_type=event_type,
        message=message,
        channels=channels,
    )

def notify_user_conversion_complete(user, task, message=None):
    if not message:
        task_ref = task.process.name
        message = f"The {task.get_step().label} for the process {task_ref} is complete. You can now access your results."
    return _create_notification(
        user=user,
        event_type=TaskNotification.EVENT_COMPLETED,
        message=message,
        task=task,
    )

def notify_user_conversion_started(user, task, message=None):
    if not message:
        task_ref = task.process.name
        message = f"The {task.get_step().label} for the process {task_ref} has started and is now running."
    return _create_notification(
        user=user,
        event_type=TaskNotification.EVENT_STARTED,
        message=message,
        task=task,
    )

def notify_user_conversion_failed(user, task, message=None):
    if not message:
        task_ref = task.process.name
        message = f"The {task.get_step().label} for the process {task_ref} has failed. Please try again."
    return _create_notification(
        user=user,
        event_type=TaskNotification.EVENT_FAILED,
        message=message,
        task=task,
    )

def notify_user_server_busy(user, task):
    message = 'The bio service server is currently at maximum capacity. Please try again later.'
    return _create_notification(
        user=user,
        event_type=TaskNotification.EVENT_WARNING,
        message=message,
        task=task,
    )


def notify_user_conversion_warning(user, task, message):
    """Create an in-app warning while task remains completed."""
    return _create_notification(
        user=user,
        event_type=TaskNotification.EVENT_WARNING,
        message=message,
        task=task,
    )
