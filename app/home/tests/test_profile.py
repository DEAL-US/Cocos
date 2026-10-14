from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notifications.models import UserNotificationSettings

User = get_user_model()


class ProfileSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user', password='Old-pass-123', email='old@example.com')
        self.client.login(username='user', password='Old-pass-123')
        self.url = reverse('accounts:profile')

    def post(self, **data):
        payload = {'email': 'old@example.com', 'current_password': '', 'new_password1': '', 'new_password2': ''}
        payload.update(data)
        return self.client.post(self.url, data=payload)

    def test_email_change_requires_current_password(self):
        response = self.post(email='attacker@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The current password is required')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old@example.com')

    def test_email_change_with_wrong_password_is_rejected(self):
        self.post(email='attacker@example.com', current_password='wrong')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old@example.com')

    def test_page_explains_that_email_change_needs_only_current_password(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'To change your email, also enter your current password below.')
        self.assertContains(response, "You don't need to set a new password.")

    def test_email_change_with_current_password_succeeds(self):
        response = self.post(email='new@example.com', current_password='Old-pass-123')
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertTrue(self.user.check_password('Old-pass-123'))

    def test_notification_toggle_without_email_change_needs_no_password(self):
        response = self.post(email_notifications_enabled='on')
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertTrue(UserNotificationSettings.objects.get(user=self.user).email_notifications_enabled)

    def test_password_change_keeps_this_session_and_ends_the_others(self):
        other_session = self.client_class()
        other_session.login(username='user', password='Old-pass-123')

        self.post(current_password='Old-pass-123', new_password1='New-pass-456', new_password2='New-pass-456')

        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = other_session.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_password_change_still_requires_current_password(self):
        self.post(new_password1='New-pass-456', new_password2='New-pass-456')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Old-pass-123'))

        self.post(current_password='Old-pass-123', new_password1='New-pass-456', new_password2='New-pass-456')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('New-pass-456'))
