from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.users.factories import make_patient
from apps.users.views import LoginRateThrottle


@override_settings(SECURE_SSL_REDIRECT=False)
class AuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.patient = make_patient()
        self.client = APIClient()

    def _login(self, password='Str0ng-pass-123'):
        return self.client.post('/api/v1/auth/login/', {'username': 'pat1', 'password': password}, format='json')

    def test_logout_revokes_refresh_token(self):
        refresh = self._login().data['refresh']
        self.assertEqual(self.client.post('/api/v1/auth/logout/', {'refresh': refresh}, format='json').status_code, 205)
        r = self.client.post('/api/v1/auth/token/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_login_is_rate_limited(self):
        with patch.object(LoginRateThrottle, 'THROTTLE_RATES', {'login': '3/min'}):
            codes = [self._login('wrong-password').status_code for _ in range(4)]
        self.assertEqual(codes[:3], [401, 401, 401])
        self.assertEqual(codes[3], 429)

    def test_unknown_username_gets_generic_message(self):
        r = self.client.post('/api/v1/auth/login/', {'username': 'PAT1', 'password': 'x'}, format='json')
        self.assertEqual(r.status_code, 401)
        self.assertNotIn('pat1', str(r.data))

    def test_common_password_rejected_on_change(self):
        self.client.force_authenticate(self.patient.user)
        r = self.client.post('/api/v1/auth/change-password/', {
            'old_password': 'Str0ng-pass-123', 'new_password': 'password123',
        }, format='json')
        self.assertEqual(r.status_code, 400)


class AuditLogTests(TestCase):
    def test_entries_cannot_be_changed_or_deleted(self):
        entry = AuditLog.objects.create(action='TEST', description='created')
        entry.description = 'tampered'
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()


@override_settings(SECURE_SSL_REDIRECT=False)
class LoginUsabilityTests(TestCase):
    def setUp(self):
        cache.clear()
        make_patient('hari.tamang')

    def test_username_is_case_insensitive(self):
        r = APIClient().post('/api/v1/auth/login/', {'username': 'Hari.Tamang', 'password': 'Str0ng-pass-123'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['username'], 'hari.tamang')

    def test_generated_passwords_avoid_look_alike_characters(self):
        from apps.users.credentials import generate_password
        for _ in range(200):
            self.assertFalse(set(generate_password()) & set('lI1O0'))


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminOnlyActionTests(TestCase):
    """Admin-only actions must refuse patients and doctors (regression: a
    get_permissions() override used to replace the per-action permissions)."""

    def setUp(self):
        from apps.users.factories import make_doctor
        self.patient = make_patient()
        self.doctor = make_doctor()

    def _as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_non_admins_cannot_reset_doctor_passwords(self):
        for user in (self.patient.user, self.doctor.user):
            r = self._as(user).post(f'/api/v1/doctors/{self.doctor.id}/reset_password/')
            self.assertEqual(r.status_code, 403)
            self.assertNotIn('new_password', getattr(r, 'data', {}) or {})
        self.doctor.user.refresh_from_db()
        self.assertTrue(self.doctor.user.check_password('Str0ng-pass-123'))

    def test_non_admins_cannot_use_patient_admin_actions(self):
        client = self._as(self.patient.user)
        self.assertEqual(client.patch(f'/api/v1/patients/{self.patient.id}/toggle_status/').status_code, 403)
        self.assertEqual(client.post(f'/api/v1/patients/{self.patient.id}/reset_password/').status_code, 403)
        self.assertEqual(client.post(f'/api/v1/patients/{self.patient.id}/regenerate_qr/').status_code, 403)
        self.assertEqual(client.get('/api/v1/patients/stats/').status_code, 403)

    def test_public_and_patient_actions_still_work(self):
        self.assertEqual(APIClient().get(f'/api/v1/patients/public/{self.patient.uuid_token}/').status_code, 200)
        self.assertEqual(self._as(self.patient.user).get('/api/v1/patients/me/').status_code, 200)
        self.assertEqual(self._as(self.doctor.user).get(f'/api/v1/patients/scan/{self.patient.uuid_token}/').status_code, 200)
