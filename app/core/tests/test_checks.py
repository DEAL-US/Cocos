from django.test import SimpleTestCase, override_settings

from core.checks import SENDGRID_BACKEND, check_email_configuration


class EmailConfigurationCheckTests(SimpleTestCase):
    @override_settings(EMAIL_BACKEND=SENDGRID_BACKEND, SENDGRID_API_KEY=None)
    def test_warns_when_sendgrid_has_no_key(self):
        self.assertEqual([warning.id for warning in check_email_configuration(None)], ['core.W001'])

    @override_settings(EMAIL_BACKEND=SENDGRID_BACKEND, SENDGRID_API_KEY='key')
    def test_passes_with_a_key(self):
        self.assertEqual(check_email_configuration(None), [])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend', SENDGRID_API_KEY=None)
    def test_ignores_other_backends(self):
        self.assertEqual(check_email_configuration(None), [])
