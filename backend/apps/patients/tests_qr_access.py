from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import User
from apps.patients.models import Patient
from apps.doctors.models import Doctor, DoctorAssignment, AccessRequest
from apps.lab_reports.models import LabReport
from apps.documents.models import Document
from apps.doctors.models import Prescription


@override_settings(SECURE_SSL_REDIRECT=False)
class QRAccessIntegrationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            username='testadmin', password='adminpass', role='ADMIN', is_active=True
        )
        self.doctor_user = User.objects.create_user(
            username='testdoctor', password='doctorpass', role='DOCTOR', is_active=True
        )
        self.patient_user = User.objects.create_user(
            username='testpatient', password='patientpass', role='PATIENT', is_active=True
        )
        self.doctor = Doctor.objects.create(
            user=self.doctor_user,
            doctor_id=Doctor.generate_doctor_id(),
            license_number='NMC-12345',
            department='General Medicine',
            specialization='General',
            dob='1980-01-01',
            gender='Male',
            phone='9800000000',
            email='doctor@test.com',
            status='Active',
        )
        self.patient = Patient.objects.create(
            user=self.patient_user,
            patient_id='PAT-7E570001',
            first_name='Test',
            last_name='Patient',
            dob='1990-01-01',
            gender='Male',
            blood_group='O+',
            phone='9800000001',
            emergency_contact='9800000002',
            email='patient@test.com',
            address='Test Address',
            height=170,
            weight=70,
            status='Active',
        )
        self.admin_token = str(RefreshToken.for_user(self.admin_user).access_token)
        self.doctor_token = str(RefreshToken.for_user(self.doctor_user).access_token)

    def authenticate(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_public_profile_restricted(self):
        url = f'/api/v1/patients/public/{self.patient.uuid_token}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('patient_id', data)
        self.assertIn('first_name', data)
        self.assertNotIn('email', data, 'Public profile should not expose email')
        self.assertNotIn('address', data, 'Public profile should not expose address')
        self.assertNotIn('height', data, 'Public profile should not expose height')
        self.assertNotIn('weight', data, 'Public profile should not expose weight')
        self.assertNotIn('allergies', data, 'Public profile should not expose allergies')

    def test_admin_scan_full_access(self):
        self.authenticate(self.admin_token)
        url = f'/api/v1/patients/scan/{self.patient.uuid_token}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['access'], 'FULL')
        self.assertIn('blood_pressure', data['patient'], 'Admin should see full clinical data')

    def test_unassigned_doctor_scan_general(self):
        self.authenticate(self.doctor_token)
        url = f'/api/v1/patients/scan/{self.patient.uuid_token}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['access'], 'GENERAL')
        self.assertIn('patient_id', data['patient'])
        self.assertNotIn('blood_pressure', data['patient'])

    def test_assigned_doctor_no_request_creates_pending(self):
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        self.authenticate(self.doctor_token)
        url = f'/api/v1/patients/scan/{self.patient.uuid_token}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['access'], 'PENDING')
        self.assertTrue(AccessRequest.objects.filter(doctor=self.doctor, patient=self.patient, status='PENDING').exists())

    def test_assigned_doctor_pending_returns_pending(self):
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        AccessRequest.objects.create(doctor=self.doctor, patient=self.patient, status='PENDING')
        self.authenticate(self.doctor_token)
        url = f'/api/v1/patients/scan/{self.patient.uuid_token}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['access'], 'PENDING')

    def test_assigned_doctor_declined_returns_declined(self):
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        AccessRequest.objects.create(doctor=self.doctor, patient=self.patient, status='DECLINED')
        self.authenticate(self.doctor_token)
        url = f'/api/v1/patients/scan/{self.patient.uuid_token}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['access'], 'DECLINED')

    def test_assigned_doctor_approved_returns_full(self):
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        AccessRequest.objects.create(doctor=self.doctor, patient=self.patient, status='APPROVED')
        self.authenticate(self.doctor_token)
        url = f'/api/v1/patients/scan/{self.patient.uuid_token}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['access'], 'FULL')
        self.assertIn('blood_pressure', data['patient'])

    def test_lab_report_denied_without_approved_request(self):
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        lab = LabReport.objects.create(
            patient=self.patient,
            file='test.pdf',
            name='Test Report',
            uploaded_by=self.admin_user,
            status='CONFIRMED',
        )
        self.authenticate(self.doctor_token)
        url = f'/api/v1/lab-reports/{lab.id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_lab_report_allowed_with_approved_request(self):
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        AccessRequest.objects.create(doctor=self.doctor, patient=self.patient, status='APPROVED')
        lab = LabReport.objects.create(
            patient=self.patient,
            file='test.pdf',
            name='Test Report',
            uploaded_by=self.admin_user,
            status='CONFIRMED',
        )
        self.authenticate(self.doctor_token)
        url = f'/api/v1/lab-reports/{lab.id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_prescription_denied_without_approved_request(self):
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        Prescription.objects.create(
            patient=self.patient,
            doctor=self.doctor_user,
            diagnosis='Test',
            medications='Test meds',
        )
        self.authenticate(self.doctor_token)
        url = '/api/v1/prescriptions/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data.get('results', data)
        self.assertEqual(len(results), 0, 'Doctor should not see prescriptions without approved access')

    def test_prescription_allowed_with_approved_request(self):
        DoctorAssignment.objects.create(doctor=self.doctor, patient=self.patient, status='Active')
        AccessRequest.objects.create(doctor=self.doctor, patient=self.patient, status='APPROVED')
        Prescription.objects.create(
            patient=self.patient,
            doctor=self.doctor_user,
            diagnosis='Test',
            medications='Test meds',
        )
        self.authenticate(self.doctor_token)
        url = '/api/v1/prescriptions/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data.get('results', data)
        self.assertEqual(len(results), 1, 'Doctor should see prescriptions with approved access')
