"""End to end: an account an admin creates (or resets) can sign in, change its
password and load its own dashboard, exactly as the frontend does it."""
import json
import re
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.users.factories import make_admin

# Same fields, as strings, that AdminPatients.tsx sends in its FormData.
PATIENT_FORM = {
    'patient_id': 'PAT-5A1E0001',
    'first_name': 'Sunita', 'middle_name': '', 'last_name': 'Maharjan', 'dob': '1992-03-14',
    'gender': 'Female', 'blood_group': 'B+', 'phone': '9841234567', 'emergency_contact': '9841234568',
    'email': 'sunita@example.com', 'address': 'Patan, Lalitpur', 'height': '158', 'weight': '54',
    'allergies': '', 'current_medication': '', 'status': 'Active',
}

# Same fields AdminDoctors.tsx sends, including the JSON-encoded schedule.
DOCTOR_FORM = {
    'first_name': 'Bishnu', 'last_name': 'Thapa', 'license_number': 'NMC-45678',
    'department': 'Pediatrics', 'specialization': 'Child health', 'dob': '1979-07-21',
    'gender': 'Male', 'phone': '9851234567', 'email': 'bishnu@example.com', 'status': 'Active',
    'availability_schedule': json.dumps({
        'Monday': '09:00-17:00', 'Tuesday': '09:00-17:00', 'Wednesday': '09:00-17:00',
        'Thursday': '09:00-17:00', 'Friday': '09:00-17:00', 'Saturday': 'closed', 'Sunday': 'closed',
    }),
}

PATIENT_DASHBOARD = ['patients/', 'appointments/', 'documents/', 'prescriptions/', 'lab-reports/',
                     'notifications/', 'recommendations/']
DOCTOR_DASHBOARD = ['patients/', 'appointments/', 'appointments/doctor/', 'prescriptions/',
                    'access-requests/', 'notifications/']

NEW_PASSWORD = 'Kathmandu-Valley-2026'


@override_settings(
    SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    FRONTEND_URL='http://localhost:5173',
)
class AdminCreatedAccountSignInTests(TestCase):
    def setUp(self):
        cache.clear()  # login rate limit
        self.admin = APIClient()
        self.admin.force_authenticate(make_admin())

    # ── helpers ──────────────────────────────────────────────────────────

    def _credentials_from_email(self):
        self.assertEqual(len(mail.outbox), 1, 'expected one welcome email')
        body = mail.outbox[0].body
        username = re.search(r'Username:\n(\S+)', body).group(1)
        password = re.search(r'Temporary Password:\n(\S+)', body).group(1)
        self.assertIn('http://localhost:5173/login', body)
        return username, password

    def _login(self, username, password):
        return APIClient().post('/api/v1/auth/login/', {'username': username, 'password': password}, format='json')

    def _sign_in_and_reach_dashboard(self, username, password, role, profile_key, endpoints):
        # 1. First sign-in with the temporary password: allowed, but a change is required.
        r = self._login(username, password)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['role'], role)
        self.assertTrue(r.data['must_change_password'])
        user = APIClient()
        user.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

        me = user.get('/api/v1/auth/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['role'], role)
        self.assertIn(profile_key, me.data, 'the dashboard needs the linked profile')

        # 2. Forced password change (what ChangePasswordPage submits).
        r = user.post('/api/v1/auth/change-password/', {'old_password': password, 'new_password': NEW_PASSWORD}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

        # 3. The temporary password stops working; the new one opens the dashboard.
        self.assertEqual(self._login(username, password).status_code, 401)
        r = self._login(username, NEW_PASSWORD)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data['must_change_password'])
        user.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        for endpoint in endpoints:
            self.assertEqual(user.get(f'/api/v1/{endpoint}').status_code, 200, endpoint)

    # ── tests ────────────────────────────────────────────────────────────

    def test_patient_signs_in_with_emailed_credentials(self):
        r = self.admin.post('/api/v1/patients/', PATIENT_FORM, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['email_sent'])
        username, password = self._credentials_from_email()
        self._sign_in_and_reach_dashboard(username, password, 'PATIENT', 'patient_profile', PATIENT_DASHBOARD)

    def test_doctor_signs_in_with_emailed_credentials(self):
        r = self.admin.post('/api/v1/doctors/', DOCTOR_FORM, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['email_sent'])
        username, password = self._credentials_from_email()
        self.assertTrue(username.startswith('dr.'))
        self._sign_in_and_reach_dashboard(username, password, 'DOCTOR', 'doctor_profile', DOCTOR_DASHBOARD)

    def test_patient_signs_in_with_credentials_shown_to_admin(self):
        with patch('apps.users.email_service.send_mail', side_effect=OSError('SMTP down')):
            r = self.admin.post('/api/v1/patients/', PATIENT_FORM, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self._sign_in_and_reach_dashboard(
            r.data['generated_username'], r.data['generated_password'],
            'PATIENT', 'patient_profile', PATIENT_DASHBOARD,
        )

    def test_doctor_signs_in_with_credentials_shown_to_admin(self):
        with patch('apps.users.email_service.send_mail', side_effect=OSError('SMTP down')):
            r = self.admin.post('/api/v1/doctors/', DOCTOR_FORM, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self._sign_in_and_reach_dashboard(
            r.data['generated_username'], r.data['generated_password'],
            'DOCTOR', 'doctor_profile', DOCTOR_DASHBOARD,
        )

    def test_reset_passwords_work_for_patient_and_doctor(self):
        self.admin.post('/api/v1/patients/', PATIENT_FORM, format='multipart')
        patient_username, _ = self._credentials_from_email()
        mail.outbox.clear()
        self.admin.post('/api/v1/doctors/', DOCTOR_FORM, format='multipart')
        doctor_username, _ = self._credentials_from_email()

        from apps.users.models import User
        for username, kind, role, profile, endpoints in (
            (patient_username, 'patients', 'PATIENT', 'patient_profile', PATIENT_DASHBOARD),
            (doctor_username, 'doctors', 'DOCTOR', 'doctor_profile', DOCTOR_DASHBOARD),
        ):
            user = User.objects.get(username=username)
            profile_id = getattr(user, profile).id
            r = self.admin.post(f'/api/v1/{kind}/{profile_id}/reset_password/')
            self.assertEqual(r.status_code, 200, r.data)
            self._sign_in_and_reach_dashboard(username, r.data['new_password'], role, profile, endpoints)

    def test_rejected_new_password_is_explained(self):
        with patch('apps.users.email_service.send_mail', side_effect=OSError('SMTP down')):
            r = self.admin.post('/api/v1/patients/', PATIENT_FORM, format='multipart')
        username, password = r.data['generated_username'], r.data['generated_password']
        token = self._login(username, password).data['access']
        user = APIClient()
        user.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        r = user.post('/api/v1/auth/change-password/', {'old_password': password, 'new_password': 'password123'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('new_password', r.data)
