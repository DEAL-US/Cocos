"""System checks for the production configuration, run with `manage.py check --deploy`."""
from django.conf import settings
from django.core.checks import Warning, register

SENDGRID_BACKEND = 'sendgrid_backend.SendgridBackend'


@register(deploy=True)
def check_email_configuration(app_configs, **kwargs):
    """Without a SendGrid key the application runs, but cannot send email notifications."""
    if settings.EMAIL_BACKEND == SENDGRID_BACKEND and not getattr(settings, 'SENDGRID_API_KEY', None):
        return [Warning(
            'SENDGRID_API_KEY is not set, so email notifications cannot be sent.',
            hint='Set SENDGRID_API_KEY in the production environment file.',
            id='core.W001',
        )]
    return []
