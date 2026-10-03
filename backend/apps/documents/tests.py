import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.documents.models import Document
from apps.users.factories import make_admin, make_doctor, make_patient

MEDIA = tempfile.mkdtemp()


def _pdf(name='report.pdf'):
    return SimpleUploadedFile(name, b'%PDF-1.4 test', content_type='application/pdf')


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class DocumentTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.admin = make_admin()
        self.patient = make_patient()
        self.other = make_patient('pat2', phone='9800000011', emergency='9800000012')
        self.client = APIClient()

    def test_admin_medical_upload_keeps_type_and_can_be_deleted(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post('/api/v1/documents/', {
            'patient': self.patient.id, 'name': 'Discharge summary', 'report_type': 'MEDICAL', 'file': _pdf(),
        }, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['report_type'], 'MEDICAL')
        self.assertEqual(r.data['uploaded_by'], self.admin.id)
        r = self.client.delete(f"/api/v1/documents/{r.data['id']}/")
        self.assertEqual(r.status_code, 204)

    def test_patient_cannot_upload_medical(self):
        self.client.force_authenticate(self.patient.user)
        r = self.client.post('/api/v1/documents/', {
            'patient': self.patient.id, 'name': 'Fake', 'report_type': 'MEDICAL', 'file': _pdf(),
        }, format='multipart')
        self.assertEqual(r.status_code, 403)

    def test_patient_cannot_move_document_to_another_patient(self):
        self.client.force_authenticate(self.patient.user)
        r = self.client.post('/api/v1/documents/', {
            'patient': self.patient.id, 'name': 'X-ray', 'file': _pdf(),
        }, format='multipart')
        doc_id = r.data['id']
        r = self.client.patch(f'/api/v1/documents/{doc_id}/', {'patient': self.other.id}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Document.objects.get(pk=doc_id).patient, self.patient)

    def test_file_url_not_exposed_and_name_is_random(self):
        self.client.force_authenticate(self.patient.user)
        r = self.client.post('/api/v1/documents/', {
            'patient': self.patient.id, 'name': 'X-ray', 'file': _pdf('my-xray.pdf'),
        }, format='multipart')
        self.assertNotIn('file', r.data)
        stored = Document.objects.get(pk=r.data['id']).file.name
        self.assertNotIn('my-xray', stored)
        r = self.client.get(f"/api/v1/documents/{r.data['id']}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])

    def test_doctor_without_access_sees_nothing(self):
        Document.objects.create(patient=self.patient, name='x', file=_pdf())
        doctor = make_doctor()
        self.client.force_authenticate(doctor.user)
        r = self.client.get('/api/v1/documents/')
        self.assertEqual(r.data['count'], 0)
