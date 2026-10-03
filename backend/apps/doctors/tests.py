from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.doctors.models import AccessRequest, Prescription
from apps.notifications.models import Notification
from apps.users.factories import grant_access, make_admin, make_doctor, make_patient


@override_settings(SECURE_SSL_REDIRECT=False)
class DoctorProfileTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.client = APIClient()
        self.client.force_authenticate(self.doctor.user)

    def test_doctor_can_update_own_contact_details(self):
        r = self.client.patch(f'/api/v1/doctors/{self.doctor.id}/', {'phone': '9822222222'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.doctor.refresh_from_db()
        self.assertEqual(self.doctor.phone, '9822222222')

    def test_doctor_cannot_change_licence_or_department(self):
        for field, value in (('license_number', 'NMC-9999'), ('department', 'Neurology')):
            r = self.client.patch(f'/api/v1/doctors/{self.doctor.id}/', {field: value}, format='json')
            self.assertEqual(r.status_code, 403, field)
        self.doctor.refresh_from_db()
        self.assertEqual(self.doctor.license_number, 'NMC-1001')
        self.assertEqual(self.doctor.department, 'Cardiology')

    def test_doctor_sees_own_full_profile(self):
        r = self.client.get(f'/api/v1/doctors/{self.doctor.id}/')
        self.assertEqual(r.data['license_number'], 'NMC-1001')


@override_settings(SECURE_SSL_REDIRECT=False)
class DoctorDirectoryPrivacyTests(TestCase):
    def test_patient_sees_public_doctor_fields_only(self):
        make_doctor()
        patient = make_patient()
        client = APIClient()
        client.force_authenticate(patient.user)
        doc = client.get('/api/v1/doctors/').data['results'][0]
        for key in ('phone', 'email', 'dob', 'license_number', 'login_username', 'user_id'):
            self.assertNotIn(key, doc)
        self.assertIn('department', doc)


@override_settings(SECURE_SSL_REDIRECT=False)
class DoctorAccessRuleTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.client = APIClient()

    def test_admin_assignment_grants_access(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post('/api/v1/assignments/', {'doctor': self.doctor.id, 'patient': self.patient.id}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(AccessRequest.objects.filter(doctor=self.doctor, patient=self.patient, status='APPROVED').exists())

        self.client.force_authenticate(self.doctor.user)
        self.assertEqual(self.client.get(f'/api/v1/patients/{self.patient.id}/').status_code, 200)
        scan = self.client.get(f'/api/v1/patients/scan/{self.patient.uuid_token}/').data
        self.assertEqual(scan['access'], 'FULL')

    def test_assignment_without_approval_gives_no_record(self):
        from apps.doctors.models import DoctorAssignment
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        self.client.force_authenticate(self.doctor.user)
        self.assertEqual(self.client.get(f'/api/v1/patients/{self.patient.id}/').status_code, 404)

    def test_prescription_needs_access_and_is_visible_afterwards(self):
        self.client.force_authenticate(self.doctor.user)
        payload = {'patient': self.patient.id, 'diagnosis': 'Flu', 'medications': 'Rest'}
        self.assertEqual(self.client.post('/api/v1/prescriptions/', payload, format='json').status_code, 403)

        grant_access(self.doctor, self.patient)
        self.assertEqual(self.client.post('/api/v1/prescriptions/', payload, format='json').status_code, 201)
        self.assertEqual(self.client.get('/api/v1/prescriptions/').data['count'], 1)

    def test_admin_cannot_write_prescriptions(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post('/api/v1/prescriptions/', {
            'patient': self.patient.id, 'diagnosis': 'Flu', 'medications': 'Rest',
        }, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Prescription.objects.exists())

    def test_approval_notifies_patient(self):
        req = AccessRequest.objects.create(doctor=self.doctor, patient=self.patient)
        self.client.force_authenticate(self.admin)
        self.client.post(f'/api/v1/access-requests/{req.id}/approve/')
        self.assertTrue(Notification.objects.filter(receiver=self.patient.user, role='PATIENT').exists())
