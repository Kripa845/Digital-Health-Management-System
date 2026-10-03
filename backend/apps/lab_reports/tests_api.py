"""Lab report API: identity gate, preview → confirm, update rules, review queue,
dashboard and security. Synthetic data only. OCR is stubbed so each test
controls the report text; RealOcrSampleTests run the real OCR on the sample files."""
import itertools
import logging
import pathlib
import shutil
import tempfile
from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.lab_reports.models import LabReport, LabResult
from apps.lab_reports.services.ocr import OcrResult
from apps.users.factories import grant_access, make_admin, make_doctor, make_patient

MEDIA = tempfile.mkdtemp()
SAMPLES = pathlib.Path(__file__).resolve().parents[2] / 'samples' / 'lab_reports'
_unique = itertools.count()


def pdf_bytes() -> bytes:
    """A distinct (tiny) PDF each time, so uploads are not treated as duplicates."""
    return b'%PDF-1.4\n% synthetic test report ' + str(next(_unique)).encode() + b'\n'


def report_text(patient, pid=None, name='Hari Tamang', age=36, report_date='14/09/2026',
                values=('Haemoglobin   13.4  g/dL', 'T. Chol   210  mg/dL', 'RBS   140  mg/dL'), extra=()):
    pid = patient.patient_id if pid is None else pid
    lines = ['CITY LAB (synthetic)']
    if pid:
        lines.append(f'Patient ID : {pid}')
    lines += [f'Patient Name : {name}     Age : {age} Y', f'Report Date : {report_date}', *values, *extra]
    return '\n'.join(lines)


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class LabApiTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()   # upload rate limit
        self.patient = make_patient('hari.tamang')   # Hari Tamang, born 1990-01-01, O+
        self.client = APIClient()
        self.client.force_authenticate(self.patient.user)

    def upload(self, text, client=None, confidence=95.0, filename='report.pdf', content=None, patient_id=None):
        data = {'name': 'Lab report', 'file': SimpleUploadedFile(filename, content or pdf_bytes())}
        if patient_id:
            data['patient'] = patient_id
        with patch('apps.lab_reports.services.upload.read_document', return_value=OcrResult(text, confidence)):
            return (client or self.client).post('/api/v1/reports/upload/', data, format='multipart')

    def confirm(self, report_id, client=None, **payload):
        return (client or self.client).post(f'/api/v1/reports/{report_id}/confirm/', payload, format='json')

    def counts(self):
        return LabReport.objects.count(), LabResult.objects.count()

    def rows(self, response):
        return {f['patient_field']: f for f in response.data['fields']}


# ── Identity gate ────────────────────────────────────────────────────────────

class IdentityGateTests(LabApiTestCase):
    def test_matching_id_gives_preview_and_writes_no_results(self):
        r = self.upload(report_text(self.patient))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION')
        self.assertTrue(r.data['identity_verified'])
        self.assertEqual(LabResult.objects.count(), 0)          # preview only
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.hemoglobin)

    def test_id_formats_are_normalised(self):
        compact = self.patient.patient_id.replace('-', '').lower()
        spaced = f'{self.patient.patient_id[:8]} {self.patient.patient_id[8:]}'
        for pid in (compact, spaced, f'PID: {self.patient.patient_id}'):
            r = self.upload(report_text(self.patient, pid=pid))
            self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', pid)

    def test_id_matched_on_its_number_part(self):
        self.patient.patient_id = 'PAT-79028232'
        self.patient.save()
        for pid in ('79028232', 'PAT 7902 8232', 'UHID: 79028232', 'pat-79028232'):
            r = self.upload(report_text(self.patient, pid=pid))
            self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', pid)

    def test_ocr_misread_id_label_still_found(self):
        """Tesseract often reads "Patient ID" as "Patient 1D" (seen on a real scan)."""
        self.patient.patient_id = 'PAT-79028232'
        self.patient.save()
        r = self.upload(report_text(self.patient, pid='', extra=('Patient 1D: 79028232',)))
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', r.data['review_reasons'])

    def test_letters_in_the_id_are_ignored(self):
        self.patient.patient_id = 'PAT-AB79028232'
        self.patient.save()
        for pid in ('79028232', 'PAT-79028232', 'PAT-XY79028232'):
            r = self.upload(report_text(self.patient, pid=pid))
            self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', (pid, r.data.get('review_reasons')))

    def test_id_in_brackets_beside_the_name(self):
        self.patient.patient_id = 'PAT-79028232'
        self.patient.save()
        for name in ('Hari Tamang (79028232)', 'Hari Tamang (PAT-79028232)', 'Hari Tamang (ID: 7902 8232)'):
            r = self.upload(report_text(self.patient, pid='', name=name))
            self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', (name, r.data.get('review_reasons')))

    def test_lab_code_with_letters_beside_the_name(self):
        """Real report: "Name: KARUNA SHRESTHA (SBHF31965)", sometimes wrapped onto the next line."""
        self.patient.patient_id = 'PAT-31965'
        self.patient.save()
        for name in ('Hari Tamang (SBHF31965)', 'Hari Tamang\n(SBHF31965)', 'Hari Tamang\n\n(SBHF31965)'):
            r = self.upload(report_text(self.patient, pid='', name=name))
            self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', (name, r.data.get('review_reasons')))

    def test_different_number_beside_the_name_needs_review(self):
        self.patient.patient_id = 'PAT-79028232'
        self.patient.save()
        r = self.upload(report_text(self.patient, pid='', name='Hari Tamang (11112222)'))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW')

    def test_ocr_lookalike_beside_the_name_needs_review(self):
        self.patient.patient_id = 'PAT-79028232'
        self.patient.save()
        r = self.upload(report_text(self.patient, pid='', name='Hari Tamang (79O28232)'))
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW')
        self.assertIn('patient_id_unclear', r.data['review_reasons'])

    def test_age_or_doctor_number_in_brackets_is_not_an_id(self):
        r = self.upload(report_text(self.patient, pid='', name='Hari Tamang (36 Y)',
                                    extra=('Doctor Name : Dr. Rai (NMC 12345)',)))
        self.assertIn('patient_id_missing', r.data['review_reasons'])

    def test_ids_of_other_lengths_matched(self):
        self.patient.patient_id = 'PAT-AB12'
        self.patient.save()
        r = self.upload(report_text(self.patient, pid='PAT-AB12'))
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION')

    def test_different_bare_number_needs_review_not_rejection(self):
        """A bare number may be the lab's own ID, so only a PAT-prefixed ID can reject."""
        r = self.upload(report_text(self.patient, pid='11112222'))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW')

    def test_mismatched_id_rejected_and_database_unchanged(self):
        before = self.counts()
        r = self.upload(report_text(self.patient, pid='PAT-7B31C9D2', name='Rina Shrestha'))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.data['code'], 'patient_id_mismatch')
        self.assertEqual(r.data['message'], 'Patient ID does not match this account.')
        self.assertNotIn('Rina', str(r.data))                    # never reveals the other person
        self.assertEqual(self.counts(), before)
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.hemoglobin)
        entry = AuditLog.objects.get(action='REJECT_LAB_REPORT')
        self.assertIn('PAT-7B****D2', entry.description)          # masked
        self.assertNotIn('7B31C9D2', entry.description)

    def test_missing_id_needs_review_and_cannot_be_confirmed(self):
        r = self.upload(report_text(self.patient, pid=''))
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW')
        self.assertIn('patient_id_missing', r.data['review_reasons'])
        c = self.confirm(r.data['id'])
        self.assertEqual(c.status_code, 409)
        self.assertEqual(c.data['code'], 'not_pending')
        self.assertEqual(LabResult.objects.count(), 0)

    def test_hospital_id_only_needs_review(self):
        r = self.upload(report_text(self.patient, pid='', extra=('UHID : 2081-004512',)))
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW')

    def test_ocr_confused_id_needs_review(self):
        confused = self.patient.patient_id[:4] + self.patient.patient_id[4:].replace('0', 'O').replace('1', 'I')
        if confused == self.patient.patient_id:   # this random ID has no 0 or 1: force one
            self.patient.patient_id = 'PAT-0E2E1001'
            self.patient.save()
            confused = 'PAT-OE2EI00I'
        r = self.upload(report_text(self.patient, pid=confused))
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW')
        self.assertIn('patient_id_unclear', r.data['review_reasons'])

    def test_name_mismatch_needs_review(self):
        r = self.upload(report_text(self.patient, name='Sita Gurung'))
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW')
        self.assertIn('name_mismatch', r.data['review_reasons'])

    def test_reprinted_old_report_with_current_age_passes(self):
        """A lab portal reprint of a 2022 report prints the patient's age today (36), not then (32)."""
        self.patient.refresh_from_db()
        current = self.patient.age
        for age in (current, current - 4):
            r = self.upload(report_text(self.patient, age=age, report_date='28/06/2022'))
            self.assertNotIn('age_mismatch', r.data['review_reasons'], age)

    def test_age_is_not_compared(self):
        """Only the patient ID (and name / date of birth) are checked; any age on the report is ignored."""
        r = self.upload(report_text(self.patient, age=80))
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', r.data['review_reasons'])
        self.assertNotIn('age', r.data['extracted'])

    def test_dob_mismatch_needs_review(self):
        r = self.upload(report_text(self.patient, extra=('DOB : 02/03/1985',)))
        self.assertIn('dob_mismatch', r.data['review_reasons'])

    def test_low_ocr_confidence_needs_review(self):
        r = self.upload(report_text(self.patient), confidence=31.0)
        self.assertIn('low_ocr_confidence', r.data['review_reasons'])

    def test_admin_upload_checked_against_selected_patient(self):
        other = make_patient('sita.gurung', phone='9800000011', emergency='9800000012',
                             first_name='Sita', last_name='Gurung')
        admin = APIClient()
        admin.force_authenticate(make_admin())
        r = self.upload(report_text(self.patient), client=admin, patient_id=other.id)
        self.assertEqual(r.data['code'], 'patient_id_mismatch')
        r = self.upload(report_text(self.patient), client=admin, patient_id=self.patient.id)
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION')


# ── Extraction and validation ───────────────────────────────────────────────

class ExtractionTests(LabApiTestCase):
    def test_synonyms(self):
        for hb in ('Hb 13.4 g/dL', 'HGB 13.4 g/dL', 'Haemoglobin 13.4 g/dL', 'Hemoglobin: 13.4 g/dL'):
            r = self.upload(report_text(self.patient, values=(hb, 'T. Chol 210 mg/dL', 'RBS 140 mg/dL')))
            rows = self.rows(r)
            self.assertEqual(rows['hemoglobin']['converted_value'], '13.4', hb)
            self.assertEqual(rows['cholesterol_total']['converted_value'], '210')
            self.assertEqual(rows['blood_sugar_random']['converted_value'], '140')

    def test_unit_conversion(self):
        r = self.upload(report_text(self.patient, values=(
            'Haemoglobin 134 g/L', 'Total Cholesterol 5.2 mmol/L', 'Random Blood Sugar 7.8 mmol/L')))
        rows = self.rows(r)
        self.assertEqual(rows['hemoglobin']['converted_value'], '13.4')
        self.assertEqual(rows['cholesterol_total']['converted_value'], '201.08')
        self.assertEqual(rows['blood_sugar_random']['converted_value'], '140.52')
        self.assertEqual(rows['blood_sugar_random']['converted_unit'], 'mg/dL')

    def test_missing_values_are_null_not_guessed(self):
        r = self.upload(report_text(self.patient, values=('Haemoglobin 13.4 g/dL',)))
        tests = r.data['extracted']['tests']
        self.assertEqual(tests['hemoglobin'], {'value': '13.4', 'unit': 'g/dL'})
        self.assertIsNone(tests['cholesterol_total'])
        self.assertIsNone(tests['blood_sugar_random'])
        self.assertEqual(set(self.rows(r)), {'hemoglobin'})

    def test_report_without_values_can_be_saved_as_document(self):
        r = self.upload(report_text(self.patient, values=('Urine colour: pale yellow',)))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data['status'], r.data['can_save_without_values']), ('NO_VALUES_SAVEABLE', True))
        self.assertEqual(r.data['fields'], [])
        self.assertEqual(LabResult.objects.count(), 0)

    def test_out_of_range_flagged_and_saved_only_when_accepted(self):
        """Tests other than the three main ones can still be accepted when out of range."""
        r = self.upload(report_text(self.patient, values=('Triglycerides 1500 mg/dL', 'RBS 140 mg/dL')))
        tg = self.rows(r)['triglycerides']
        self.assertEqual((tg['change_status'], tg['flag']), ('SKIPPED', 'out_of_range'))
        self.confirm(r.data['id'])
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.triglycerides)
        self.assertEqual(str(self.patient.blood_sugar_random), '140.00')

        r = self.upload(report_text(self.patient, report_date='20/09/2026',
                                    values=('Triglycerides 1500 mg/dL', 'RBS 150 mg/dL')))
        c = self.confirm(r.data['id'], accept_flagged=['triglycerides'])
        self.assertEqual(c.status_code, 200, c.data)
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.triglycerides), '1500.00')

    def test_out_of_range_main_value_dropped_and_never_saved(self):
        r = self.upload(report_text(self.patient, values=('Haemoglobin 45 g/dL', 'T. Chol 210 mg/dL')))
        hb = self.rows(r)['hemoglobin']
        self.assertEqual((hb['change_status'], hb['flag']), ('SKIPPED', 'invalid'))
        self.assertIn('3–25 g/dL', hb['skip_reason'])
        c = self.confirm(r.data['id'], accept_flagged=['hemoglobin'])      # accepting does not help
        self.assertEqual(c.status_code, 200, c.data)
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.hemoglobin)
        self.assertEqual(str(self.patient.cholesterol_total), '210.00')
        self.assertFalse(LabResult.objects.filter(test_name='hemoglobin').exists())

    def test_typed_out_of_range_main_value_refused(self):
        r = self.upload(report_text(self.patient))
        c = self.confirm(r.data['id'], values={'cholesterol_total': '650'})
        self.assertEqual((c.status_code, c.data['code']), (400, 'invalid_values'))

    def test_report_with_only_out_of_range_values_changes_nothing(self):
        before = self.counts()
        r = self.upload(report_text(self.patient, values=('Haemoglobin 45 g/dL', 'Total Cholesterol 900 mg/dL')))
        self.assertEqual((r.status_code, r.data['code']), (422, 'values_not_usable'))   # not a no-values report
        self.assertIn('Nothing was saved', r.data['message'])
        self.assertEqual(self.counts(), before)


# ── Confirm and update rules ─────────────────────────────────────────────────

class ConfirmRulesTests(LabApiTestCase):
    def test_confirm_applies_values_and_keeps_history(self):
        r = self.upload(report_text(self.patient))
        c = self.confirm(r.data['id'])
        self.assertEqual(c.status_code, 200, c.data)
        self.assertEqual(c.data['status'], 'CONFIRMED')
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '13.40')
        self.assertEqual(str(self.patient.cholesterol_total), '210.00')
        self.assertEqual(LabResult.objects.filter(patient=self.patient).count(), 3)
        self.assertTrue(AuditLog.objects.filter(action='CONFIRM_LAB_REPORT').exists())

    def test_edited_values_are_revalidated(self):
        r = self.upload(report_text(self.patient))
        bad = self.confirm(r.data['id'], values={'hemoglobin': 'thirteen'})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.data['code'], 'invalid_values')
        self.assertIn('hemoglobin', bad.data['errors'])
        self.assertEqual(LabResult.objects.count(), 0)            # nothing written

        good = self.confirm(r.data['id'], values={'hemoglobin': '13.9'})
        self.assertEqual(good.status_code, 200, good.data)
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '13.90')

    def test_unrelated_fields_cannot_be_injected(self):
        r = self.upload(report_text(self.patient, values=('Haemoglobin 13.4 g/dL',)))
        c = self.confirm(r.data['id'], values={'hba1c': '5.0'})
        self.assertEqual(c.status_code, 400)
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.hba1c)

    def test_confirm_only_once(self):
        r = self.upload(report_text(self.patient))
        self.confirm(r.data['id'])
        self.assertEqual(self.confirm(r.data['id']).status_code, 409)
        self.assertEqual(LabResult.objects.count(), 3)

    def test_blood_group_conflict_is_flagged_not_overwritten(self):
        r = self.upload(report_text(self.patient, extra=('Blood Group : AB +ve',)))
        row = self.rows(r)['blood_group']
        self.assertEqual((row['change_status'], row['flag']), ('SKIPPED', 'blood_group_conflict'))
        self.confirm(r.data['id'])
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.blood_group, 'O+')

    def test_blood_group_set_when_empty(self):
        self.patient.blood_group = ''
        self.patient.save()
        r = self.upload(report_text(self.patient, extra=('Blood Group : AB +ve',)))
        self.confirm(r.data['id'])
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.blood_group, 'AB+')

    def test_age_never_taken_from_report(self):
        r = self.upload(report_text(self.patient, age=37))
        self.confirm(r.data['id'])
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.dob), '1990-01-01')

    def test_older_report_goes_to_history_only(self):
        newer = self.upload(report_text(self.patient, report_date='14/09/2026', values=('Haemoglobin 13.4 g/dL',)))
        self.confirm(newer.data['id'])
        older = self.upload(report_text(self.patient, report_date='01/03/2026', values=('Haemoglobin 15.1 g/dL',)))
        self.assertEqual(self.rows(older)['hemoglobin']['change_status'], 'HISTORY')
        self.assertEqual(self.confirm(older.data['id']).data['code'], 'older_report_not_acknowledged')
        c = self.confirm(older.data['id'], acknowledge_older_report=True)
        self.assertEqual(self.rows(c)['hemoglobin']['change_status'], 'HISTORY')
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '13.40')
        history = list(LabResult.objects.filter(patient=self.patient, test_name='hemoglobin')
                       .order_by('report_date').values_list('report_date', 'value'))
        self.assertEqual(history, [(date(2026, 3, 1), '15.10'), (date(2026, 9, 14), '13.40')])

    def test_cancel_deletes_preview(self):
        r = self.upload(report_text(self.patient))
        self.assertEqual(self.client.post(f"/api/v1/reports/{r.data['id']}/discard/").status_code, 204)
        self.assertFalse(LabReport.objects.filter(pk=r.data['id']).exists())


# ── Files and duplicates ─────────────────────────────────────────────────────

class FileTests(LabApiTestCase):
    def test_duplicate_upload_rejected(self):
        content = pdf_bytes()
        self.assertEqual(self.upload(report_text(self.patient), content=content).status_code, 201)
        r = self.upload(report_text(self.patient), content=content)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['code'], 'duplicate')

    def test_renamed_file_rejected(self):
        r = self.upload(report_text(self.patient), content=b'MZ\x90\x00 not a pdf')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'invalid_file')

    def test_wrong_type_and_size(self):
        self.assertEqual(self.upload('x', filename='report.exe').data['code'], 'invalid_file')
        big = b'%PDF-1.4\n' + b'0' * (10 * 1024 * 1024 + 1)
        self.assertEqual(self.upload('x', content=big).data['code'], 'file_too_large')

    def test_unreadable_file(self):
        from apps.lab_reports.services.ocr import UnreadableFile
        with patch('apps.lab_reports.services.upload.read_document', side_effect=UnreadableFile('Corrupt PDF.')):
            r = self.client.post('/api/v1/reports/upload/',
                                 {'name': 'x', 'file': SimpleUploadedFile('r.pdf', pdf_bytes())}, format='multipart')
        self.assertEqual((r.status_code, r.data['code']), (400, 'unreadable'))

    def test_file_encrypted_at_rest_and_download_decrypts(self):
        content = pdf_bytes()
        r = self.upload(report_text(self.patient), content=content)
        report = LabReport.objects.get(pk=r.data['id'])
        with report.file.open('rb') as fh:
            self.assertNotIn(b'%PDF', fh.read())
        d = self.client.get(f"/api/v1/reports/{report.id}/download/")
        self.assertEqual(b''.join(d.streaming_content), content)

    def test_report_text_and_identity_not_returned_to_patient(self):
        r = self.upload(report_text(self.patient, name='Hari Tamang'))
        self.assertNotIn('ocr_text', r.data)
        self.assertNotIn('identity', r.data)
        self.assertNotIn(self.patient.patient_id, str(r.data['extracted']))


# ── Access control ───────────────────────────────────────────────────────────

class AccessTests(LabApiTestCase):
    def test_requires_login(self):
        r = APIClient().post('/api/v1/reports/upload/', {}, format='multipart')
        self.assertEqual(r.status_code, 401)

    def test_patient_cannot_see_or_confirm_another_patients_report(self):
        r = self.upload(report_text(self.patient))
        stranger = make_patient('sita.gurung', phone='9800000011', emergency='9800000012',
                                first_name='Sita', last_name='Gurung')
        other = APIClient()
        other.force_authenticate(stranger.user)
        for call in (lambda: other.get(f"/api/v1/reports/{r.data['id']}/"),
                     lambda: other.get(f"/api/v1/reports/{r.data['id']}/status/"),
                     lambda: other.post(f"/api/v1/reports/{r.data['id']}/confirm/"),
                     lambda: other.get(f"/api/v1/reports/{r.data['id']}/download/")):
            self.assertEqual(call().status_code, 404)
        self.assertEqual(other.get('/api/v1/reports/').data['count'], 0)

    def test_doctor_sees_confirmed_reports_only_with_access(self):
        r = self.upload(report_text(self.patient))
        doctor = make_doctor()
        client = APIClient()
        client.force_authenticate(doctor.user)
        self.assertEqual(client.get('/api/v1/reports/').data['count'], 0)
        grant_access(doctor, self.patient)
        self.assertEqual(client.get('/api/v1/reports/').data['count'], 0)    # not confirmed yet
        self.confirm(r.data['id'])
        self.assertEqual(client.get('/api/v1/reports/').data['count'], 1)
        self.assertEqual(client.post(f"/api/v1/reports/{r.data['id']}/confirm/").status_code, 403)

    def test_status_endpoint(self):
        r = self.upload(report_text(self.patient, pid=''))
        s = self.client.get(f"/api/v1/reports/{r.data['id']}/status/")
        self.assertEqual(s.data['status'], 'NEEDS_REVIEW')
        self.assertTrue(s.data['review_messages'])


# ── Admin review ─────────────────────────────────────────────────────────────

class ReviewQueueTests(LabApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = APIClient()
        self.admin.force_authenticate(make_admin())

    def test_queue_and_approve_then_confirm(self):
        r = self.upload(report_text(self.patient, pid=''))
        queue = self.admin.get('/api/v1/admin/review-queue/')
        self.assertEqual([q['id'] for q in queue.data], [r.data['id']])
        self.assertEqual(queue.data[0]['identity']['name'], 'Hari Tamang')
        a = self.admin.post(f"/api/v1/admin/reports/{r.data['id']}/resolve/", {'decision': 'approve'}, format='json')
        self.assertEqual(a.data['status'], 'PENDING_CONFIRMATION')
        self.assertEqual(LabResult.objects.count(), 0)           # approving applies nothing
        self.assertEqual(self.confirm(r.data['id']).status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '13.40')

    def test_reject_deletes_file(self):
        r = self.upload(report_text(self.patient, pid=''))
        report = LabReport.objects.get(pk=r.data['id'])
        storage, path = report.file.storage, report.file.name
        a = self.admin.post(f"/api/v1/admin/reports/{report.id}/resolve/",
                            {'decision': 'reject', 'note': 'Not this patient'}, format='json')
        self.assertEqual(a.data['status'], 'REJECTED')
        self.assertFalse(storage.exists(path))

    def test_only_admins(self):
        r = self.upload(report_text(self.patient, pid=''))
        self.assertEqual(self.client.get('/api/v1/admin/review-queue/').status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/admin/reports/{r.data['id']}/resolve/",
                                          {'decision': 'approve'}, format='json').status_code, 403)


# ── Dashboard ────────────────────────────────────────────────────────────────

class DashboardTests(LabApiTestCase):
    def test_dashboard_latest_status_history_trend(self):
        for day, hb in (('01/06/2026', '14.8'), ('14/09/2026', '12.1')):
            r = self.upload(report_text(self.patient, report_date=day, values=(f'Haemoglobin {hb} g/dL',)))
            self.confirm(r.data['id'])
        d = self.client.get('/api/v1/dashboard/').data
        self.patient.refresh_from_db()
        self.assertEqual(d['age'], self.patient.age)
        self.assertEqual(d['blood_group'], 'O+')
        hb = next(t for t in d['tests'] if t['test'] == 'hemoglobin')
        self.assertEqual(hb['latest'], {'value': '12.10', 'date': '2026-09-14'})
        self.assertEqual(hb['status'], 'Low')                    # male range 13.5–17.5
        self.assertEqual([p['value'] for p in hb['history']], [14.8, 12.1])
        self.assertEqual(hb['trend'], 'down')
        self.assertEqual(d['disclaimer'], 'Informational only, not medical advice.')

    def test_dashboard_scoped_to_own_record(self):
        stranger = make_patient('sita.gurung', phone='9800000011', emergency='9800000012')
        d = self.client.get(f'/api/v1/dashboard/?patient={stranger.id}').data
        self.assertEqual(d['patient_id'], self.patient.patient_id)   # query ignored for patients
        doctor = APIClient()
        doctor.force_authenticate(make_doctor().user)
        self.assertEqual(doctor.get(f'/api/v1/dashboard/?patient={self.patient.id}').status_code, 403)


# ── Logging ──────────────────────────────────────────────────────────────────

class NoPatientDataInLogsTests(LabApiTestCase):
    def test_logs_hold_no_values_or_full_ids(self):
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = records.append
        root = logging.getLogger()
        old = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            r = self.upload(report_text(self.patient))
            self.confirm(r.data['id'])
            self.upload(report_text(self.patient, pid='PAT-7B31C9D2', name='Rina Shrestha'))
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        text = '\n'.join(rec.getMessage() for rec in records)
        for secret in ('Hari', 'Tamang', 'Rina', '13.4', '210', '140', '7B31C9D2', self.patient.patient_id):
            self.assertNotIn(secret, text)


# ── Real OCR on the sample files ────────────────────────────────────────────

def _tesseract_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class RealOcrSampleTests(TestCase):
    """The e2e patient's sample reports, read for real (no OCR stub)."""

    def setUp(self):
        from django.core.management import call_command
        cache.clear()
        call_command('seed_e2e', stdout=open(__import__('os').devnull, 'w'))
        from apps.patients.models import Patient
        self.patient = Patient.objects.get(patient_id='PAT-0E2E0001')
        self.client = APIClient()
        self.client.force_authenticate(self.patient.user)

    def post(self, name):
        return self.client.post('/api/v1/reports/upload/', {
            'name': name, 'file': SimpleUploadedFile(name, (SAMPLES / name).read_bytes()),
        }, format='multipart')

    def test_matching_text_pdf_end_to_end(self):
        r = self.post('report_match.pdf')
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', r.data)
        rows = {f['patient_field']: f for f in r.data['fields']}
        self.assertEqual(rows['cholesterol_total']['converted_value'], '201.08')   # 5.2 mmol/L
        self.assertEqual(rows['blood_group']['change_status'], 'UNCHANGED')        # O +ve = O+
        self.client.post(f"/api/v1/reports/{r.data['id']}/confirm/", {}, format='json')
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '12.80')

    def test_mismatching_pdf_rejected(self):
        before = (LabReport.objects.count(), LabResult.objects.count())
        r = self.post('report_mismatch.pdf')
        self.assertEqual(r.data['code'], 'patient_id_mismatch')
        self.assertEqual((LabReport.objects.count(), LabResult.objects.count()), before)

    def test_scanned_report_without_card_id_needs_review(self):
        if not _tesseract_available():
            self.skipTest('Tesseract is not installed')
        r = self.post('report_needs_review.png')
        self.assertEqual(r.data['status'], 'NEEDS_REVIEW', r.data)
        self.assertIn('patient_id_missing', r.data['review_reasons'])


class SkipReasonTests(LabApiTestCase):
    def test_unaccepted_out_of_range_keeps_its_reason(self):
        r = self.upload(report_text(self.patient, values=('Triglycerides 1500 mg/dL', 'Haemoglobin 13.4 g/dL')))
        c = self.confirm(r.data['id'])
        reason = self.rows(c)['triglycerides']['skip_reason']
        self.assertEqual(reason, 'Outside the expected range (10–1000 mg/dL), so it may have been misread. '
                                 'Not saved because it was not accepted.')


class DeleteReportTests(LabApiTestCase):
    """Deleting a report: any status; a confirmed one takes its values off the dashboard."""

    def confirmed(self, report_date='14/09/2026', values=None):
        kwargs = {'report_date': report_date}
        if values:
            kwargs['values'] = values
        r = self.upload(report_text(self.patient, **kwargs))
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', r.data.get('review_reasons'))
        self.assertEqual(self.confirm(r.data['id']).status_code, 200)
        return r.data['id']

    def delete(self, report_id, client=None):
        return (client or self.client).delete(f'/api/v1/reports/{report_id}/')

    def test_deleting_only_report_clears_dashboard_values(self):
        report_id = self.confirmed()
        self.patient.refresh_from_db()
        self.assertIsNotNone(self.patient.hemoglobin)

        self.assertEqual(self.delete(report_id).status_code, 204)
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.hemoglobin)
        self.assertIsNone(self.patient.cholesterol_total)
        self.assertEqual(self.counts(), (0, 0))
        entry = AuditLog.objects.get(action='DELETE_LAB_REPORT')
        self.assertIn('dashboard values reverted', entry.description)
        self.assertNotIn('13.4', entry.description)               # never values

    def test_deleting_newest_report_falls_back_to_previous_value(self):
        self.confirmed('01/06/2026', values=('Haemoglobin   12.0  g/dL',))
        newest = self.confirmed('14/09/2026', values=('Haemoglobin   14.2  g/dL',))
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '14.20')

        self.delete(newest)
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '12.00')
        dash = self.client.get('/api/v1/dashboard/').data
        hb = next(t for t in dash['tests'] if t['test'] == 'hemoglobin')
        self.assertEqual([p['value'] for p in hb['history']], [12.0])

    def test_value_changed_by_hand_since_is_kept(self):
        report_id = self.confirmed()
        self.patient.refresh_from_db()
        self.patient.hemoglobin = '11.10'
        self.patient.save()
        self.delete(report_id)
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '11.10')

    def test_pending_and_in_review_reports_can_be_deleted(self):
        pending = self.upload(report_text(self.patient)).data
        review = self.upload(report_text(self.patient, pid='')).data
        self.assertEqual((pending['status'], review['status']), ('PENDING_CONFIRMATION', 'NEEDS_REVIEW'))
        for r in (pending, review):
            self.assertEqual(self.delete(r['id']).status_code, 204)
        self.assertEqual(self.counts(), (0, 0))

    def test_admin_can_delete_but_other_patient_and_doctor_cannot(self):
        report_id = self.confirmed()
        other = make_patient('sita.gurung', phone='9800000011', emergency='9800000012')
        stranger = APIClient()
        stranger.force_authenticate(other.user)
        self.assertEqual(self.delete(report_id, stranger).status_code, 404)
        doctor = make_doctor()
        grant_access(doctor, self.patient)
        doc = APIClient()
        doc.force_authenticate(doctor.user)
        self.assertEqual(self.delete(report_id, doc).status_code, 403)
        admin = APIClient()
        admin.force_authenticate(make_admin())
        self.assertEqual(self.delete(report_id, admin).status_code, 204)


# ── Reading the file: PDF text layer, OCR, flexible labels, AI fallback ─────

def text_pdf(lines, columns=False) -> bytes:
    """A digital PDF with a real text layer. With columns=True each table row is
    drawn label column first, then value column (as many lab systems do)."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    rows = []
    for line in lines:
        if columns and '|' in line:
            rows.append((y, *line.split('|', 1)))
        else:
            page.insert_text((50, y), line, fontsize=10)
        y += 16
    for y, label, _ in rows:
        page.insert_text((50, y), label.strip(), fontsize=10)
    for y, _, value in rows:
        page.insert_text((300, y), value.strip(), fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def scanned_pdf() -> bytes:
    """A PDF with no text layer: one page that is only a (blank) picture."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 200, 100), False)
    pix.set_rect(pix.irect, (255,))
    page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def llm_reply(patient_id, hb='13.2', chol=None, sugar='118'):
    import json
    item = lambda value, unit: None if value is None else {'value': value, 'unit': unit}  # noqa: E731
    return json.dumps({'hemoglobin': item(hb, 'g/dL'), 'total_cholesterol': item(chol, 'mg/dL'),
                       'blood_sugar': item(sugar, 'mg/dL'), 'patient_id': patient_id})


class ReadingTests(LabApiTestCase):
    def post_file(self, content, filename='report.pdf'):
        data = {'name': 'Lab report', 'file': SimpleUploadedFile(filename, content)}
        return self.client.post('/api/v1/reports/upload/', data, format='multipart')

    def header(self):
        return [f'Patient ID : {self.patient.patient_id}', 'Patient Name : Hari Tamang     Age : 36 Y',
                'Report Date : 14/09/2026']

    def test_digital_pdf_with_standard_labels(self):
        pdf = text_pdf(self.header() + ['Haemoglobin|13.4 g/dL', 'Total Cholesterol|210 mg/dL',
                                        'Random Blood Sugar|140 mg/dL'], columns=True)
        with self.assertLogs('apps.lab_reports.services.upload', level='INFO') as logs:
            r = self.post_file(pdf)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', r.data['review_reasons'])
        rows = self.rows(r)
        self.assertEqual((rows['hemoglobin']['converted_value'], rows['cholesterol_total']['converted_value'],
                          rows['blood_sugar_random']['converted_value']), ('13.4', '210', '140'))
        self.assertEqual(r.data['ocr_confidence'], 100.0)
        line = next(m for m in logs.output if 'Lab report read' in m)
        self.assertIn('source=text_layer', line)
        self.assertIn('values_from=regex', line)
        for secret in ('Hari', 'Tamang', self.patient.patient_id, '13.4', '210'):
            self.assertNotIn(secret, '\n'.join(logs.output))

    def test_labels_with_different_wording(self):
        for values in (('HGB ...... 13.6 g/dL', 'Cholesterol, Total   198 mg/dL', 'Glucose - Random  132 mg/dL'),
                       ('Hb (Cyanmeth method)   12.9 gm/dl', 'Cholesterol,Total: 205', 'Blood Sugar  145 mg/dL')):
            r = self.upload(report_text(self.patient, values=values))
            self.assertEqual(r.status_code, 201, (values, r.data))
            found = {k: f['converted_value'] for k, f in self.rows(r).items()}
            self.assertEqual(set(found) >= {'hemoglobin', 'cholesterol_total', 'blood_sugar_random'}, True, found)
            self.client.post(f"/api/v1/reports/{r.data['id']}/discard/")

    def test_fasting_sugar_is_not_read_as_random(self):
        r = self.upload(report_text(self.patient, values=('Haemoglobin 13.4 g/dL', 'Blood Sugar Fasting 99 mg/dL')))
        rows = self.rows(r)
        self.assertNotIn('blood_sugar_random', rows)
        self.assertEqual(rows['blood_sugar_fasting']['converted_value'], '99')

    @override_settings(LAB_LLM_FALLBACK=True, ANTHROPIC_API_KEY='test-key')
    def test_scanned_pdf_uses_ai_fallback(self):
        with patch('apps.lab_reports.services.llm._ask', return_value=llm_reply(self.patient.patient_id)) as ask, \
                self.assertLogs('apps.lab_reports.services.upload', level='INFO') as logs:
            r = self.post_file(scanned_pdf())
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION', r.data['review_reasons'])
        images = ask.call_args.args[0]
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].startswith(b'\x89PNG'))
        rows = self.rows(r)
        self.assertEqual((rows['hemoglobin']['converted_value'], rows['blood_sugar_random']['converted_value']),
                         ('13.2', '118'))
        self.assertIn('values_from=llm', next(m for m in logs.output if 'Lab report read' in m))
        self.assertTrue(AuditLog.objects.filter(action='UPLOAD_LAB_REPORT',
                                                description__contains='AI fallback').exists())

    @override_settings(LAB_LLM_FALLBACK=True, ANTHROPIC_API_KEY='test-key')
    def test_ai_fallback_reply_with_another_patients_id_is_rejected(self):
        before = self.counts()
        with patch('apps.lab_reports.services.llm._ask', return_value=llm_reply('PAT-7B31C9D2')):
            r = self.post_file(scanned_pdf())
        self.assertEqual((r.status_code, r.data['code']), (422, 'patient_id_mismatch'))
        self.assertEqual(self.counts(), before)

    @override_settings(LAB_LLM_FALLBACK=True, ANTHROPIC_API_KEY='test-key')
    def test_invalid_ai_reply_is_ignored(self):
        for reply in ('The haemoglobin is 13.2', '{"hemoglobin": "about 13"}',
                      llm_reply(None, hb='13,2'), llm_reply(None)[:-1] + ', "extra": 1}'):
            with patch('apps.lab_reports.services.llm._ask', return_value=reply):
                r = self.post_file(scanned_pdf())
            self.assertEqual((r.status_code, r.data['status']), (201, 'NO_VALUES_SAVEABLE'), reply)
            self.client.post(f"/api/v1/reports/{r.data['id']}/discard/")

    @override_settings(LAB_LLM_FALLBACK=True, ANTHROPIC_API_KEY='test-key')
    def test_ai_fallback_out_of_range_value_dropped(self):
        with patch('apps.lab_reports.services.llm._ask', return_value=llm_reply(None, hb='45', sugar=None)):
            r = self.post_file(scanned_pdf())
        self.assertEqual((r.status_code, r.data['code']), (422, 'values_not_usable'))

    def test_ai_fallback_off_by_default(self):
        with patch('apps.lab_reports.services.llm._ask') as ask:
            r = self.post_file(scanned_pdf())
        ask.assert_not_called()
        # A blank scan: no values and nothing to identify the patient by, so it can only
        # be kept as an unverified document.
        self.assertEqual((r.status_code, r.data['status'], r.data['identity_verified']),
                         (201, 'NO_VALUES_SAVEABLE', False))

    def test_ai_fallback_not_used_when_text_has_values(self):
        with override_settings(LAB_LLM_FALLBACK=True, ANTHROPIC_API_KEY='test-key'), \
                patch('apps.lab_reports.services.llm._ask') as ask:
            r = self.upload(report_text(self.patient))
        ask.assert_not_called()
        self.assertEqual(r.status_code, 201)

    def test_corrupt_pdf_is_unreadable(self):
        r = self.post_file(b'%PDF-1.4\n%this is not really a pdf\n')
        self.assertEqual((r.status_code, r.data['code']), (400, 'unreadable'))
        self.assertIn('damaged', r.data['message'])

    def test_corrupt_image_is_unreadable(self):
        r = self.post_file(b'\x89PNG\r\n\x1a\n' + b'broken' * 20, filename='scan.png')
        self.assertEqual((r.status_code, r.data['code']), (400, 'unreadable'))

    def test_empty_report_can_be_saved_as_document(self):
        r = self.post_file(text_pdf(self.header() + ['Urine routine examination', 'Colour: pale yellow',
                                                     'Appearance: clear', 'Comment: within normal limits']))
        self.assertEqual((r.status_code, r.data['status'], r.data['identity_verified']),
                         (201, 'NO_VALUES_SAVEABLE', True))
        self.assertEqual(r.data['no_values_message'], 'No health card values were found. You can save this report '
                                                      'as a document only. Dashboard values will not change.')
        self.assertEqual(LabResult.objects.count(), 0)


class ReadPdfTests(TestCase):
    def test_returns_text_and_page_images(self):
        from apps.lab_reports.ocr_service import read_pdf
        text, images = read_pdf(text_pdf(['Haemoglobin|13.4 g/dL', 'RBS|140 mg/dL'], columns=True))
        self.assertIn('Haemoglobin  13.4 g/dL', text)          # label and value on one row
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].startswith(b'\x89PNG'))

    def test_image_goes_straight_to_the_image_list(self):
        from apps.lab_reports.ocr_service import read_pdf
        png = (SAMPLES / 'report_match.png').read_bytes()
        self.assertEqual(read_pdf(png), ('', [png]))

    def test_password_protected_pdf(self):
        import pymupdf
        from apps.lab_reports.ocr_service import read_pdf
        doc = pymupdf.open()
        doc.new_page().insert_text((50, 72), 'secret')
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw='pw', owner_pw='pw')
        with self.assertRaisesRegex(RuntimeError, 'password'):
            read_pdf(data)


class ScannedTableTests(LabApiTestCase):
    def test_ocr_words_regrouped_into_table_rows(self):
        """Tesseract lists a table column by column; rows are rebuilt from word positions."""
        from apps.lab_reports.ocr_service import _join_rows
        # (x0, y0, x1, y1, text): the label column first, then the result column.
        words = [(50, 100, 160, 112, 'Haemoglobin'), (50, 130, 150, 142, 'Platelets'),
                 (400, 101, 440, 113, '13.13'), (450, 101, 480, 113, 'g/dl'), (400, 131, 440, 143, '277')]
        self.assertEqual(_join_rows(words).splitlines(), ['Haemoglobin  13.13 g/dl', 'Platelets  277'])

    def test_decimal_comma_read_as_decimal_point(self):
        r = self.upload(report_text(self.patient, values=('Haemoglobin  13,13  g/dL', 'T. Chol 210 mg/dL')))
        self.assertEqual(self.rows(r)['hemoglobin']['converted_value'], '13.13')

    def test_number_stuck_to_letters_is_not_a_result(self):
        r = self.upload(report_text(self.patient, values=('RBC Count (Blood)  a4l  10^6/uL', 'Haemoglobin 13.4 g/dL')))
        self.assertNotIn('rbc_count', self.rows(r))


class DashboardExtraTestsTests(LabApiTestCase):
    def test_other_confirmed_tests_appear_on_the_dashboard(self):
        r = self.upload(report_text(self.patient, values=('Haemoglobin 13.4 g/dL', 'Blood Urea  13.81 mg/dL',
                                                          'SGPT  18.89 U/L', 'Potassium  4.0 mEq/L')))
        self.assertEqual(self.confirm(r.data['id']).status_code, 200)
        tests = {t['test']: t for t in self.client.get('/api/v1/dashboard/').data['tests']}
        self.assertEqual(list(tests)[:3], ['hemoglobin', 'cholesterol_total', 'blood_sugar_random'])
        self.assertEqual(tests['blood_urea']['latest']['value'], '13.81')
        self.assertEqual((tests['blood_urea']['status'], tests['blood_urea']['reference']), ('Low', '15–45 mg/dL'))
        self.assertEqual(tests['ssgpt_alt']['status'], 'Normal')
        self.assertEqual(tests['potassium']['history'], [{'date': '2026-09-14', 'value': 4.0}])
        self.assertNotIn('tsh', tests)                       # no result, no tile

    def test_reference_text_is_rounded(self):
        hba1c = next(t for t in self.client.get('/api/v1/dashboard/').data['tests'] if t['test'] == 'hba1c')
        self.assertEqual(hba1c['reference'], 'below 5.7 %')


class HbA1cTests(LabApiTestCase):
    def test_hba1c_read_in_ocr_spellings(self):
        """OCR reads "HbA1C" as "HbAIC" (I for 1), seen on a real scanned report."""
        for line, expected in (('HbAIC  5.8  %  4-57', '5.8'), ('HbA1C 6.1 %', '6.1'), ('HbAlC: 7.2 %', '7.2'),
                               ('Hb A1c 5.4 %', '5.4'), ('Glycated Haemoglobin (HbA1c)  6.4 %', '6.4'),
                               ('Haemoglobin A1c 6.2 %', '6.2')):
            r = self.upload(report_text(self.patient, values=(line, 'T. Chol 210 mg/dL')))
            rows = self.rows(r)
            self.assertEqual(rows['hba1c']['converted_value'], expected, line)
            self.assertNotIn('hemoglobin', rows, line)          # not taken as the haemoglobin result
            self.client.post(f"/api/v1/reports/{r.data['id']}/discard/")

    def test_haemoglobin_not_taken_from_mean_cell_haemoglobin(self):
        r = self.upload(report_text(self.patient, values=('Mean Cell Haemoglobin  29.8 pg',
                                                          'Haemoglobin  13.13 g/dL', 'HbAIC  5.8 %')))
        rows = self.rows(r)
        self.assertEqual((rows['hemoglobin']['converted_value'], rows['hba1c']['converted_value']), ('13.13', '5.8'))

