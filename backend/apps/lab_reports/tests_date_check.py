"""Report date ordering check: a new report compared with the patient's latest confirmed report."""
import logging
from datetime import date

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.lab_reports.identity import extract_identity, parse_date
from apps.lab_reports.models import LabReport, LabResult
from apps.lab_reports.services.date_check import (
    DATE_MISSING, FIRST_REPORT, OK, OLDER_THAN_LATEST, check_report_date,
)
from apps.lab_reports.tests_api import LabApiTestCase, report_text
from apps.users.factories import make_admin, make_patient

TODAY = date(2026, 10, 3)


class CheckReportDateTests(SimpleTestCase):
    """The pure comparison function."""

    def test_statuses(self):
        latest = date(2026, 9, 14)
        self.assertEqual(check_report_date(date(2026, 9, 1), None), FIRST_REPORT)
        self.assertEqual(check_report_date(date(2026, 9, 20), latest), OK)
        self.assertEqual(check_report_date(latest, latest), OK)                  # same day: accepted
        self.assertEqual(check_report_date(date(2026, 9, 13), latest), OLDER_THAN_LATEST)
        self.assertEqual(check_report_date(None, latest), DATE_MISSING)
        self.assertEqual(check_report_date(None, None), DATE_MISSING)


class DateExtractionTests(SimpleTestCase):
    def test_ocr_misreads_inside_dates(self):
        self.assertEqual(parse_date('l4/O9/2026', TODAY), date(2026, 9, 14))
        self.assertEqual(parse_date('2O26-O9-l4 16:l7', TODAY), date(2026, 9, 14))
        self.assertEqual(parse_date('I4.O9.2O26', TODAY), date(2026, 9, 14))
        self.assertEqual(parse_date('14 Sep 2026', TODAY), date(2026, 9, 14))   # month names untouched

    def test_day_month_order_follows_the_setting(self):
        self.assertEqual(parse_date('04/05/2026', TODAY), date(2026, 5, 4))      # default DMY
        with override_settings(LAB_REPORT_DATE_ORDER='MDY'):
            self.assertEqual(parse_date('04/05/2026', TODAY), date(2026, 4, 5))
            self.assertEqual(parse_date('14/09/2026', TODAY), date(2026, 9, 14))  # unambiguous either way
        self.assertEqual(parse_date('09/14/2026', TODAY), date(2026, 9, 14))     # DMY, but 14 cannot be a month

    def test_reporting_date_chosen_over_other_dates(self):
        text = ('Registered Date: 01/09/2026\nCollection Date: 12/09/2026\nPrinted on: 20/09/2026\n'
                'DOB: 01/01/1990    Reporting Date: 14/09/2026 16:17:14\nDate: 02/09/2026')
        found = extract_identity(text, TODAY)
        self.assertEqual((found.report_date, found.report_date_source), (date(2026, 9, 14), 'reporting'))

    def test_collection_date_used_only_without_a_reporting_date(self):
        found = extract_identity('Sample Collected on: 12/09/2026\nPrinted on: 20/09/2026', TODAY)
        self.assertEqual((found.report_date, found.report_date_source), (date(2026, 9, 12), 'collection'))
        found = extract_identity('Registered Date: 01/09/2026\nPrinted: 20/09/2026\nDate: 02/09/2026', TODAY)
        self.assertEqual((found.report_date, found.report_date_source), (None, ''))

    def test_future_and_bikram_sambat_dates_rejected(self):
        self.assertIsNone(extract_identity('Report Date: 14/09/2027', TODAY).report_date)
        self.assertIsNone(extract_identity('Report Date: 2081/05/28', TODAY).report_date)


class ReportDateOrderingTests(LabApiTestCase):
    def confirmed(self, report_date, value='13.4', patient=None):
        patient = patient or self.patient
        r = self.upload(report_text(patient, report_date=report_date, values=(f'Haemoglobin {value} g/dL',)))
        self.assertEqual(r.status_code, 201, r.data)
        c = self.confirm(r.data['id'], acknowledge_older_report=True)
        self.assertEqual(c.status_code, 200, c.data)
        return r.data['id']

    def preview(self, report_date, value='12.0'):
        r = self.upload(report_text(self.patient, report_date=report_date, values=(f'Haemoglobin {value} g/dL',)))
        self.assertEqual(r.status_code, 201, r.data)
        return r

    def test_first_report(self):
        r = self.preview('14/09/2026')
        self.assertEqual((r.data['date_check_status'], r.data['latest_report_date'], r.data['date_message']),
                         (FIRST_REPORT, None, ''))
        self.assertEqual((r.data['report_date'], r.data['report_date_source']), ('2026-09-14', 'reporting'))
        self.assertEqual(self.confirm(r.data['id']).status_code, 200)

    def test_later_and_same_date_are_ok(self):
        self.confirmed('14/09/2026')
        for d in ('14/09/2026', '20/09/2026'):          # same day, then later
            r = self.preview(d, value='12.5' if d.startswith('20') else '12.6')
            self.assertEqual((r.data['date_check_status'], r.data['date_ack_required'], r.data['date_message']),
                             (OK, False, ''), d)
            self.assertEqual(self.confirm(r.data['id']).status_code, 200, d)

    def test_older_report_needs_acknowledgement_and_only_adds_history(self):
        self.confirmed('14/09/2026', value='13.4')
        r = self.preview('01/03/2026', value='15.1')
        self.assertEqual((r.data['date_check_status'], r.data['latest_report_date']), (OLDER_THAN_LATEST, '2026-09-14'))
        self.assertTrue(r.data['date_ack_required'])
        self.assertEqual(r.data['date_message'], 'This report (1 Mar 2026) is older than your latest report (14 Sep 2026).')

        refused = self.confirm(r.data['id'])
        self.assertEqual((refused.status_code, refused.data['code']), (400, 'older_report_not_acknowledged'))
        self.assertEqual(LabReport.objects.get(pk=r.data['id']).status, 'PENDING_CONFIRMATION')
        self.assertEqual(LabResult.objects.count(), 1)                           # nothing applied

        ok = self.confirm(r.data['id'], acknowledge_older_report=True)
        self.assertEqual(ok.status_code, 200, ok.data)
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '13.40')                 # latest value kept
        self.assertEqual(LabResult.objects.filter(report_id=r.data['id']).count(), 1)   # history added
        self.assertTrue(AuditLog.objects.filter(action='OVERRIDE_OLDER_REPORT_DATE').exists())

    @override_settings(LAB_REPORT_OLDER_DATE_POLICY='block')
    def test_block_policy_refuses_and_stores_nothing(self):
        self.confirmed('14/09/2026')
        before = self.counts()
        r = self.upload(report_text(self.patient, report_date='01/03/2026', values=('Haemoglobin 15.1 g/dL',)))
        self.assertEqual((r.status_code, r.data['code']), (422, 'older_report'))
        self.assertIn('older than your latest report', r.data['message'])
        self.assertEqual(self.counts(), before)

    @override_settings(LAB_REPORT_OLDER_DATE_POLICY='allow')
    def test_allow_policy_has_no_warning(self):
        self.confirmed('14/09/2026')
        r = self.preview('01/03/2026')
        self.assertEqual((r.data['date_check_status'], r.data['date_ack_required'], r.data['date_message']),
                         (OLDER_THAN_LATEST, False, ''))
        self.assertEqual(self.confirm(r.data['id']).status_code, 200)

    def test_missing_date_then_manual_entry(self):
        self.confirmed('14/09/2026')
        r = self.preview('')
        self.assertEqual((r.data['date_check_status'], r.data['report_date']), (DATE_MISSING, None))
        self.assertIn('No reporting date could be read', r.data['date_message'])

        older = self.client.post(f"/api/v1/reports/{r.data['id']}/report-date/", {'report_date': '2026-03-01'}, format='json')
        self.assertEqual(older.status_code, 200, older.data)
        self.assertEqual((older.data['date_check_status'], older.data['report_date'], older.data['report_date_source'],
                          older.data['report_date_user_entered']), (OLDER_THAN_LATEST, '2026-03-01', 'user', True))
        self.assertEqual(self.rows(older)['hemoglobin']['change_status'], 'HISTORY')   # preview planned again

        later = self.client.post(f"/api/v1/reports/{r.data['id']}/report-date/", {'report_date': '2026-09-30'}, format='json')
        self.assertEqual(later.data['date_check_status'], OK)
        self.assertEqual(self.rows(later)['hemoglobin']['change_status'], 'UPDATED')

    def test_manual_date_validated(self):
        r = self.preview('')
        url = f"/api/v1/reports/{r.data['id']}/report-date/"
        for bad in ('2099-01-01', 'not a date', ''):
            res = self.client.post(url, {'report_date': bad}, format='json')
            self.assertEqual((res.status_code, res.data['code']), (400, 'invalid_date'), bad)

    @override_settings(LAB_REPORT_OLDER_DATE_POLICY='block')
    def test_block_policy_refuses_an_older_manual_date(self):
        self.confirmed('14/09/2026')
        r = self.preview('')
        res = self.client.post(f"/api/v1/reports/{r.data['id']}/report-date/", {'report_date': '2026-03-01'}, format='json')
        self.assertEqual((res.status_code, res.data['code']), (422, 'older_report'))
        self.assertIsNone(LabReport.objects.get(pk=r.data['id']).report_date)

    def test_another_patients_reports_do_not_count(self):
        other = make_patient('sita.date', phone='9800000041', emergency='9800000042', first_name='Sita', last_name='Gurung')
        other_client = APIClient()
        other_client.force_authenticate(other.user)
        up = self.upload(report_text(other, name='Sita Gurung', report_date='30/09/2026'), client=other_client)
        self.assertEqual(self.confirm(up.data['id'], client=other_client).status_code, 200)
        self.assertEqual(self.preview('01/03/2026').data['date_check_status'], FIRST_REPORT)

    def test_unconfirmed_and_deleted_reports_do_not_count(self):
        self.preview('30/09/2026', value='12.1')                               # never confirmed
        self.assertEqual(self.preview('01/03/2026').data['date_check_status'], FIRST_REPORT)

        older_id = self.confirmed('01/06/2026', value='12.2')
        newest_id = self.confirmed('14/09/2026', value='12.3')
        r = self.preview('10/08/2026', value='12.4')
        self.assertEqual((r.data['date_check_status'], r.data['latest_report_date']), (OLDER_THAN_LATEST, '2026-09-14'))
        self.client.delete(f'/api/v1/reports/{newest_id}/')                     # falls back to the next latest
        again = self.client.get(f"/api/v1/reports/{r.data['id']}/").data
        self.assertEqual((again['date_check_status'], again['latest_report_date']), (OK, '2026-06-01'))
        self.assertTrue(LabReport.objects.filter(pk=older_id).exists())

    def test_admin_upload_compared_with_the_chosen_patient(self):
        self.confirmed('14/09/2026')
        admin = APIClient()
        admin.force_authenticate(make_admin())
        r = self.upload(report_text(self.patient, report_date='01/03/2026'), client=admin, patient_id=self.patient.id)
        self.assertEqual(r.data['date_check_status'], OLDER_THAN_LATEST)

    def test_logs_contain_no_dates_names_ids_or_values(self):
        self.confirmed('14/09/2026')
        with self.assertLogs(level=logging.INFO) as logs:
            r = self.preview('01/03/2026', value='15.1')
            self.confirm(r.data['id'], acknowledge_older_report=True)
            self.client.post(f"/api/v1/reports/{r.data['id']}/report-date/", {'report_date': '2026-02-01'}, format='json')
        text = '\n'.join(logs.output)
        self.assertIn('status=older_than_latest', text)
        for secret in ('2026-03-01', '01/03/2026', '1 Mar 2026', '2026-09-14', '14 Sep 2026', 'Hari', 'Tamang',
                       self.patient.patient_id, '15.1', '13.4'):
            self.assertNotIn(secret, text)
        audit = ' '.join(AuditLog.objects.values_list('description', flat=True))
        for secret in ('2026-03-01', '1 Mar 2026', '14 Sep 2026', '15.1'):
            self.assertNotIn(secret, audit)
