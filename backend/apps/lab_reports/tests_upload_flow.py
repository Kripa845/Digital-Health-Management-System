"""Pure-function tests for report reading: name/age identity helpers, units,
layouts and spellings. API tests live in tests_api.py."""
import logging
import shutil
import tempfile
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.lab_reports.identity import extract_identity, names_match, parse_date, verify_identity
from apps.lab_reports.models import LabReport, LabReportField
from apps.lab_reports.units import convert
from apps.users.factories import grant_access, make_admin, make_doctor, make_patient

MEDIA = tempfile.mkdtemp()
TODAY = date(2026, 10, 1)


class FixedDate(date):
    """Pins "today" for age and report-date checks."""
    @classmethod
    def today(cls):
        return TODAY
PDF = b'%PDF-1.4\n% test report\n'

# Patient made by make_patient(): Hari Tamang, born 1990-01-01 (36 on TODAY).
GOOD_REPORT = (
    'City Diagnostic Lab\n'
    'Patient Name : Mr. Hari Tamang        Age/Sex : 36 Y / M\n'
    'Ref. Dr. : Dr. Arjun Sharma\n'
    'Report Date : 14/09/2026\n'
    'Haemoglobin        13.4     g/dL      13.5-17.5\n'
    'Fasting Blood Sugar  5.4    mmol/L    3.9-5.5\n'
    'Total Cholesterol    210    mg/dL     <200\n'
)


def _upload(name='Lipid profile', content=PDF, filename='report.pdf'):
    return {'name': name, 'file': SimpleUploadedFile(filename, content, content_type='application/pdf')}


# ── Pure functions ────────────────────────────────────────────────────────────

class NameMatchTests(SimpleTestCase):
    def test_titles_case_and_order_ignored(self):
        self.assertTrue(names_match('MR. HARI TAMANG', 'Hari', 'Tamang'))
        self.assertTrue(names_match('Tamang Hari', 'Hari', 'Tamang'))

    def test_small_ocr_errors_allowed(self):
        self.assertTrue(names_match('Harl Tamang', 'Hari', 'Tamang'))
        self.assertTrue(names_match('Hari Tamanq', 'Hari', 'Tamang'))

    def test_middle_name_optional_but_must_match_if_present(self):
        self.assertTrue(names_match('Hari Tamang', 'Hari', 'Tamang', 'Bahadur'))
        self.assertTrue(names_match('Hari Bahadur Tamang', 'Hari', 'Tamang', 'Bahadur'))
        self.assertFalse(names_match('Hari Prasad Tamang', 'Hari', 'Tamang', 'Bahadur'))

    def test_different_people_rejected(self):
        self.assertFalse(names_match('Sita Tamang', 'Hari', 'Tamang'))
        self.assertFalse(names_match('Hari Gurung', 'Hari', 'Tamang'))
        self.assertFalse(names_match('H. Tamang', 'Hari', 'Tamang'))


class IdentityTests(SimpleTestCase):
    patient = SimpleNamespace(first_name='Hari', middle_name='', last_name='Tamang', dob=date(1990, 1, 1))

    def test_extracts_name_and_date_not_the_doctor(self):
        found = extract_identity(GOOD_REPORT, today=TODAY)
        self.assertEqual(found.name, 'Hari Tamang')
        self.assertEqual(found.report_date, date(2026, 9, 14))
        self.assertFalse(hasattr(found, 'age'))              # the age is not read from reports

    def test_matching_report_verified(self):
        self.assertTrue(verify_identity(extract_identity(GOOD_REPORT, TODAY), self.patient, TODAY).verified)

    def test_age_is_not_checked(self):
        for text in (GOOD_REPORT.replace('36 Y', '52 Y'), 'Patient Name: Hari Tamang\nHaemoglobin 13.4 g/dL'):
            self.assertTrue(verify_identity(extract_identity(text, TODAY), self.patient, TODAY).verified)

    def test_missing_name_rejected(self):
        no_name = 'Age: 36\nHaemoglobin 13.4 g/dL'
        self.assertIn('name could not be found', verify_identity(extract_identity(no_name, TODAY), self.patient, TODAY).reason)

    def test_date_of_birth_is_checked_when_printed(self):
        text = 'Name: Hari Tamang  DOB: 02/02/1985'
        self.assertFalse(verify_identity(extract_identity(text, TODAY), self.patient, TODAY).verified)
        text = 'Name: Hari Tamang  DOB: 01/01/1990'
        self.assertTrue(verify_identity(extract_identity(text, TODAY), self.patient, TODAY).verified)

    def test_reason_never_contains_report_contents(self):
        text = GOOD_REPORT.replace('Hari Tamang', 'Sita Gurung')
        reason = verify_identity(extract_identity(text, TODAY), self.patient, TODAY).reason
        self.assertNotIn('Sita', reason)

    def test_devanagari_record_name_cannot_be_verified(self):
        patient = SimpleNamespace(first_name='हरि', middle_name='', last_name='तामाङ', dob=date(1990, 1, 1))
        result = verify_identity(extract_identity(GOOD_REPORT, TODAY), patient, TODAY)
        self.assertFalse(result.verified)
        self.assertIn('English letters', result.reason)

    def test_dates(self):
        self.assertEqual(parse_date('14/09/2026', TODAY), date(2026, 9, 14))
        self.assertEqual(parse_date('2026-09-14', TODAY), date(2026, 9, 14))
        self.assertEqual(parse_date('14 Sep 2026', TODAY), date(2026, 9, 14))
        self.assertIsNone(parse_date('2083/05/28', TODAY))   # Bikram Sambat
        self.assertIsNone(parse_date('14/09/2027', TODAY))   # future


class UnitTests(SimpleTestCase):
    def test_conversions(self):
        self.assertEqual(convert('blood_sugar_fasting', '5.4', 'mmol/L').value, '97.29')
        self.assertEqual(convert('cholesterol_total', '5.2', 'mmol/L').value, '201.08')
        self.assertEqual(convert('triglycerides', '1.5', 'mmol/l').value, '132.86')
        self.assertEqual(convert('hemoglobin', '132', 'g/L').value, '13.2')
        self.assertEqual(convert('hemoglobin', '13.2', 'g%').value, '13.2')
        self.assertEqual(convert('hba1c', '48', 'mmol/mol').value, '6.54')

    def test_unknown_unit_rejected(self):
        result = convert('blood_sugar_fasting', '97', 'g/L')
        self.assertIsNone(result.value)
        self.assertIn('not recognised', result.error)

    def test_missing_unit_assumes_dashboard_unit(self):
        self.assertEqual(convert('hemoglobin', '13.4', '').value, '13.4')


# ── API flow ──────────────────────────────────────────────────────────────────

class UnitSurvivesNormalisationTests(SimpleTestCase):
    def test_litre_before_reference_range_is_kept(self):
        from apps.lab_reports.extractor import extract_medical_fields
        fields = {f.patient_field: f for f in extract_medical_fields('Fasting Blood Sugar  5.4  mmol/L  3.9-5.5')}
        self.assertEqual(fields['blood_sugar_fasting'].unit.lower(), 'mmol/l')


class HaemoglobinSpellingTests(SimpleTestCase):
    def test_british_us_and_ocr_misread_spellings_all_match(self):
        from apps.lab_reports.extractor import extract_medical_fields
        for text in ('Haemoglobin 13.4 g/dL', 'HAEMOGLOBIN : 13.4 gm/dl', 'Hemoglobin: 13.4 g/dL',
                     'Hb 13.4 g%', 'Haemoglobln 13.4 g/dL', 'Hemog1obin 13.4', 'Haemogl0bin: 13.4 g/dL'):
            fields = {f.patient_field: f for f in extract_medical_fields(text)}
            self.assertEqual(fields['hemoglobin'].extracted_value, '13.4', text)
            self.assertEqual(fields['hemoglobin'].field_name, 'Haemoglobin', text)

    def test_hba1c_is_not_read_as_haemoglobin(self):
        from apps.lab_reports.extractor import extract_medical_fields
        fields = {f.patient_field for f in extract_medical_fields('HbA1c 6.1 %')}
        self.assertEqual(fields, {'hba1c'})


class ReportLayoutTests(SimpleTestCase):
    """Name and age are found in the layouts real reports use."""
    patient = SimpleNamespace(first_name='Hari', middle_name='', last_name='Tamang', dob=date(1990, 1, 1))

    def _check(self, text):
        return verify_identity(extract_identity(text, TODAY), self.patient, TODAY)

    def test_layouts_that_must_match(self):
        layouts = {
            'colon': 'Patient Name : Hari Tamang      Age : 36 Y',
            'no colon': 'Patient Name   Hari Tamang      Age 36 Years',
            'OCR separators': 'Patient Name . Hari Tamang   Age ; 36',
            'value below label': 'Patient Name\nHari Tamang\nAge\n36 Years',
            'digital PDF columns': 'Patient Name\nAge / Sex\nRef. By\n: Mr. Hari Tamang\n: 36 Y / M\n: Dr. A Sharma',
            'referrer first': 'Referred By: Dr. A Sharma      Patient Name: Hari Tamang   Age: 36',
            'sex in brackets': 'Name : HARI TAMANG (M)   Age : 36 Yrs',
            'OCR Narne': 'Narne : Hari Tamang   Age : 36',
            'table pipes': '| Patient Name | Hari Tamang | Age | 36 Y |',
            'relation': 'Name: Hari Tamang S/O Ram Tamang   Age: 36',
            'no labels': 'CITY LAB\nHari Tamang    36 Y / M\nHaemoglobin 13.4',
            'generated by': 'Report generated by City Lab   Patient Name: Hari Tamang  Age: 36',
            'table header row': 'Patient Name   Age / Sex\nMr. Hari Tamang     36 Y / M',
            'header row, OCR spacing': 'Patient Name Age/ Sex\nMr. Hari Tamang 36 Y/M',
        }
        for label, text in layouts.items():
            self.assertTrue(self._check(text).verified, label)

    def test_layouts_that_must_not_match(self):
        self.assertFalse(self._check('Patient Name : Sita Gurung   Age : 36').verified)
        self.assertFalse(self._check('Patient Name : Sita Gurung   Age : 36\nRef. Dr: Hari Tamang').verified)
        self.assertFalse(self._check('Consultant: Dr. Hari Tamang\nAge 36').verified)
        self.assertFalse(self._check('CITY LAB\nDr. Hari Tamang    36 Y\nHaemoglobin 13.4').verified)


class MiddleNameTests(SimpleTestCase):
    def test_one_extra_middle_name_allowed_when_record_has_none(self):
        self.assertTrue(names_match('Hari Bahadur Tamang', 'Hari', 'Tamang'))
        self.assertTrue(names_match('Sita Kumari Gurung', 'Sita', 'Gurung'))

    def test_more_than_one_extra_word_rejected(self):
        self.assertFalse(names_match('Hari Bahadur Prasad Tamang', 'Hari', 'Tamang'))

    def test_recorded_middle_name_must_agree(self):
        self.assertFalse(names_match('Hari Prasad Tamang', 'Hari', 'Tamang', 'Bahadur'))

    def test_extra_word_must_sit_between_first_and_last_name(self):
        self.assertFalse(names_match('Hari Tamang Sharma', 'Hari', 'Tamang'))
        self.assertFalse(names_match('Ram Hari Tamang', 'Hari', 'Tamang'))
        self.assertTrue(names_match('Tamang Bahadur Hari', 'Hari', 'Tamang'))
