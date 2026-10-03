"""Reports with no health card values can be kept as documents (status SAVED_NO_VALUES)."""
import io
import logging
from datetime import timedelta

from django.core.files.storage import default_storage
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.lab_reports.models import LabReport, LabResult
from apps.lab_reports.tests_api import LabApiTestCase, report_text
from apps.users.factories import make_admin, make_doctor, grant_access

URINE = ('Urine routine examination', 'Colour: pale yellow', 'Appearance: clear', 'pH: 6.0')
THYROID_NOTE = ('Thyroid ultrasound', 'Impression: normal study', 'Comment: no nodules seen')


class NoValuesSaveTests(LabApiTestCase):
    def upload_no_values(self, lines=URINE, **kwargs):
        r = self.upload(report_text(self.patient, values=lines), **kwargs)
        self.assertEqual(r.status_code, 201, r.data)
        return r

    def stored_path(self, report_id):
        return LabReport.objects.get(pk=report_id).file.name

    def test_no_values_report_is_saveable_then_saved_as_document_only(self):
        self.patient.refresh_from_db()
        before_hb = self.patient.hemoglobin
        for lines in (URINE, THYROID_NOTE):
            r = self.upload_no_values(lines)
            self.assertEqual(r.data['status'], 'NO_VALUES_SAVEABLE')
            self.assertTrue(r.data['can_save_without_values'])
            self.assertTrue(r.data['identity_verified'])
            self.assertIn('You can save this report as a document only', r.data['no_values_message'])
            self.assertEqual(r.data['fields'], [])

            c = self.confirm(r.data['id'])
            self.assertEqual(c.status_code, 200, c.data)
            self.assertEqual((c.data['status'], c.data['updated_count']), ('SAVED_NO_VALUES', 0))
            report = LabReport.objects.get(pk=r.data['id'])
            self.assertTrue(report.file and default_storage.exists(report.file.name))   # the file is kept
            self.assertTrue(report.is_encrypted)
            self.assertIsNotNone(report.confirmed_at)

        self.assertEqual(LabResult.objects.count(), 0)                                 # no value or history rows
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.hemoglobin, before_hb)
        dashboard = self.client.get('/api/v1/dashboard/').data
        self.assertFalse(any(t['latest'] for t in dashboard['tests']))                   # dashboard unchanged
        self.assertEqual(AuditLog.objects.filter(action='SAVE_LAB_REPORT_NO_VALUES').count(), 2)

    def test_saved_document_listed_with_its_status(self):
        r = self.upload_no_values()
        self.confirm(r.data['id'])
        listed = self.client.get('/api/v1/reports/').data['results']
        self.assertEqual([(x['id'], x['status']) for x in listed], [(r.data['id'], 'SAVED_NO_VALUES')])

    def test_cancel_stores_nothing_and_removes_the_file(self):
        before = self.counts()
        r = self.upload_no_values()
        path = self.stored_path(r.data['id'])
        self.assertTrue(default_storage.exists(path))
        self.assertEqual(self.client.post(f"/api/v1/reports/{r.data['id']}/discard/").status_code, 204)
        self.assertEqual(self.counts(), before)
        self.assertFalse(default_storage.exists(path))

    def test_unconfirmed_no_values_preview_expires(self):
        r = self.upload_no_values()
        path = self.stored_path(r.data['id'])
        LabReport.objects.filter(pk=r.data['id']).update(uploaded_at=timezone.now() - timedelta(hours=25))
        out = io.StringIO()
        call_command('purge_lab_uploads', stdout=out)
        self.assertIn('Deleted 1 unconfirmed', out.getvalue())
        self.assertFalse(LabReport.objects.filter(pk=r.data['id']).exists())
        self.assertFalse(default_storage.exists(path))

    def test_recent_preview_and_saved_documents_are_not_purged(self):
        saved = self.upload_no_values()
        self.confirm(saved.data['id'])
        LabReport.objects.filter(pk=saved.data['id']).update(uploaded_at=timezone.now() - timedelta(days=3))
        recent = self.upload_no_values(THYROID_NOTE)
        from apps.lab_reports.services.upload import purge_stale_previews
        self.assertEqual(purge_stale_previews(), 0)
        self.assertEqual(LabReport.objects.filter(pk__in=[saved.data['id'], recent.data['id']]).count(), 2)

    def test_another_patients_id_still_rejected(self):
        before = self.counts()
        r = self.upload(report_text(self.patient, pid='PAT-7B31C9D2', name='Rina Shrestha', values=URINE))
        self.assertEqual((r.status_code, r.data['code']), (422, 'patient_id_mismatch'))
        self.assertEqual(self.counts(), before)

    def test_duplicate_file_still_blocked(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch
        from apps.lab_reports.services.ocr import OcrResult
        content = b'%PDF-1.4\n% one fixed synthetic no-values report\n'
        text = report_text(self.patient, values=URINE)
        with patch('apps.lab_reports.services.upload.read_document', return_value=OcrResult(text, 95.0)):
            first = self.client.post('/api/v1/reports/upload/', {'file': SimpleUploadedFile('a.pdf', content)}, format='multipart')
            again = self.client.post('/api/v1/reports/upload/', {'file': SimpleUploadedFile('a.pdf', content)}, format='multipart')
        self.assertEqual(first.status_code, 201)
        self.assertEqual((again.status_code, again.data['code']), (409, 'duplicate'))

    def test_delete_saved_document_removes_file_and_record(self):
        r = self.upload_no_values()
        self.confirm(r.data['id'])
        path = self.stored_path(r.data['id'])
        self.assertEqual(self.client.delete(f"/api/v1/reports/{r.data['id']}/").status_code, 204)
        self.assertFalse(LabReport.objects.filter(pk=r.data['id']).exists())
        self.assertFalse(default_storage.exists(path))

    def test_all_values_out_of_range_is_not_saved_as_document(self):
        before = self.counts()
        r = self.upload(report_text(self.patient, values=('Haemoglobin 45 g/dL', 'RBS 950 mg/dL')))
        self.assertEqual((r.status_code, r.data['code']), (422, 'values_not_usable'))
        self.assertIn('outside the expected ranges', r.data['message'])
        self.assertEqual(self.counts(), before)

    def test_flagged_values_keep_the_tick_to_accept_preview(self):
        r = self.upload(report_text(self.patient, values=('Triglycerides 1500 mg/dL',)))
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION')               # not converted to a document
        self.assertEqual(self.rows(r)['triglycerides']['flag'], 'out_of_range')

    def test_review_still_goes_to_an_admin_then_can_be_saved(self):
        r = self.upload(report_text(self.patient, name='Sita Gurung', values=URINE))   # name does not match
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW')
        self.assertEqual(self.confirm(r.data['id']).status_code, 409)               # not until reviewed
        admin = APIClient()
        admin.force_authenticate(make_admin())
        res = admin.post(f"/api/v1/admin/reports/{r.data['id']}/resolve/", {'decision': 'approve'}, format='json')
        self.assertEqual(res.data['status'], 'NO_VALUES_SAVEABLE')
        self.assertEqual(self.confirm(r.data['id']).data['status'], 'SAVED_NO_VALUES')

    def test_older_date_warning_applies_and_saved_documents_count_for_dates(self):
        saved = self.upload(report_text(self.patient, report_date='14/09/2026', values=URINE))
        self.assertEqual(self.confirm(saved.data['id']).data['status'], 'SAVED_NO_VALUES')
        older = self.upload(report_text(self.patient, report_date='01/03/2026', values=THYROID_NOTE))
        self.assertEqual((older.data['date_check_status'], older.data['latest_report_date']),
                         ('older_than_latest', '2026-09-14'))                   # the saved document counted
        self.assertEqual(self.confirm(older.data['id']).data['code'], 'older_report_not_acknowledged')
        self.assertEqual(self.confirm(older.data['id'], acknowledge_older_report=True).data['status'], 'SAVED_NO_VALUES')

    def test_doctor_with_access_sees_saved_document_not_previews(self):
        saved = self.upload_no_values()
        self.confirm(saved.data['id'])
        preview = self.upload_no_values(THYROID_NOTE)
        doctor = make_doctor()
        grant_access(doctor, self.patient)
        doc = APIClient()
        doc.force_authenticate(doctor.user)
        ids = [x['id'] for x in doc.get('/api/v1/reports/', {'patient': self.patient.id}).data['results']]
        self.assertIn(saved.data['id'], ids)
        self.assertNotIn(preview.data['id'], ids)

    def test_logs_hold_no_names_ids_values_or_dates(self):
        with self.assertLogs(level=logging.INFO) as logs:
            r = self.upload(report_text(self.patient, report_date='14/09/2026', values=URINE + ('Glucose (urine): nil',)))
            self.confirm(r.data['id'])
        text = '\n'.join(logs.output)
        self.assertIn('status=NO_VALUES_SAVEABLE', text)
        for secret in ('Hari', 'Tamang', self.patient.patient_id, '14/09/2026', '2026-09-14', '6.0', 'pale yellow'):
            self.assertNotIn(secret, text)
        audit = AuditLog.objects.get(action='SAVE_LAB_REPORT_NO_VALUES').description
        self.assertNotIn(self.patient.patient_id, audit)                           # masked
        self.assertIn('saved without card values', audit)
