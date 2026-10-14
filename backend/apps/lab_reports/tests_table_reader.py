"""Reading lab values row by row from a report's results table (services/table_reader.py).

FixtureTableTests runs every report in test_fixtures/lab_reports/ through the real
pipeline and compares with expected_results.csv; to cover a new lab's layout, add its
(anonymised) report and rows there - see that folder's README. The other classes test
the pieces: exact name matching, range/unit parsing, the decimal auto-fix, conflicts,
and the preview / confirm behaviour of the values read.
"""
import csv
import pathlib
import shutil
import tempfile
from decimal import Decimal, InvalidOperation
from unittest import skipUnless
from unittest.mock import patch

import pymupdf

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.lab_reports.extractor import ExtractedField
from apps.lab_reports.models import LabReport, LabResult
from apps.lab_reports.ocr_service import has_text_layer, read_pdf_pages, tesseract_available
from apps.lab_reports.services import review, table_reader as t
from apps.lab_reports.services import validator as v
from apps.lab_reports.services.extractor import ExtractedReport
from apps.lab_reports.services.ocr import OcrResult, read_document
from apps.lab_reports.services.test_names import alias_map, match_test
from apps.lab_reports.units import convert, normalise_unit
from apps.users.factories import make_patient

FIXTURES = pathlib.Path(__file__).resolve().parent / 'test_fixtures' / 'lab_reports'
MEDIA = tempfile.mkdtemp()


# ── The fixtures table ───────────────────────────────────────────────────────

def _expected() -> dict[str, list[dict]]:
    with open(FIXTURES / 'expected_results.csv', encoding='utf-8', newline='') as fh:
        rows = list(csv.DictReader(fh))
    by_file: dict[str, list[dict]] = {}
    for row in rows:
        by_file.setdefault(row['file'], []).append(row)
    return by_file


def _number(text):
    try:
        return Decimal(str(text))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _range(text: str):
    """(low, high) from "3.5-5.1", "<200", ">40"; None for "not_read"."""
    text = (text or '').strip()
    if text == 'not_read':
        return None
    if text.startswith('<'):
        return None, _number(text[1:])
    if text.startswith('>'):
        return _number(text[1:]), None
    low, high = text.split('-')
    return _number(low), _number(high)


def _flagged_for_review(ef: ExtractedField) -> bool:
    """Whether the preview would hold this value back for the user (mirrors dashboard._plan):
    a reason found while reading, a failed plausibility/unit check, or a confirmation reason."""
    value = ef.suggested_value or ef.extracted_value
    if ef.review_reasons or v.check_value(ef.patient_field, value, ef.unit).flag:
        return True
    return bool(review.reasons_for(value, ef.unit, ef.ocr_confidence, ef.reference_range))


def read_fixture(name: str):
    raw = (FIXTURES / name).read_bytes()
    ext = pathlib.Path(name).suffix.lower()
    ocr = read_document(raw, ext)
    return ocr, t.read_values(raw, ext, ocr)


def _check_fixture(self, name: str, expected: list[dict]):
    ocr, found = read_fixture(name)
    if ocr.source != 'text_layer' and not tesseract_available():
        self.skipTest('Tesseract is not installed; scanned fixtures need OCR.')
    values = {ef.patient_field: ef for ef in found.values}
    wanted = [e for e in expected if e['test'] != 'unmatched']
    self.assertEqual(sorted(values), sorted(e['test'] for e in wanted),
                     f'{name}: the tests read differ from expected_results.csv')
    for e in wanted:
        ef = values[e['test']]
        with self.subTest(file=name, test=e['test']):
            got = _number(ef.suggested_value or ef.extracted_value)
            ref = review.parse_reference_range(ef.reference_range)
            want = _range(e['range'])
            value_ok = got == _number(e['value'])
            range_ok = (ref is None) if want is None else (
                ref is not None and (_number(ref.low) if ref.low is not None else None,
                                     _number(ref.high) if ref.high is not None else None) == want)
            unit_ok = not e['unit'] or normalise_unit(ef.unit) == normalise_unit(e['unit'])
            if e['check'] == 'safe':
                self.assertTrue((value_ok and unit_ok and (range_ok or ref is None)) or _flagged_for_review(ef),
                                f'{e["test"]}: read {ef.extracted_value} ({ef.reference_range or "no range"}) '
                                'without being flagged for review')
                continue
            self.assertEqual(got, _number(e['value']), f'{e["test"]} value')
            self.assertTrue(range_ok, f'{e["test"]}: range {ef.reference_range!r}, expected {e["range"]}')
            self.assertTrue(unit_ok, f'{e["test"]}: unit {ef.unit!r}, expected {e["unit"]!r}')
            self.assertEqual(_flagged_for_review(ef) if e['check'] == 'review' else bool(ef.review_reasons),
                             e['check'] == 'review', f'{e["test"]}: review reasons {ef.review_reasons}')
    unmatched = [e['value'] for e in expected if e['test'] == 'unmatched']
    self.assertEqual(sorted(u['name'] for u in found.unmatched), sorted(unmatched), f'{name}: unmatched rows')


class FixtureTableTests(SimpleTestCase):
    """One test per report in expected_results.csv (generated below)."""


for _name, _rows in _expected().items():
    def _test(self, name=_name, rows=_rows):
        _check_fixture(self, name, rows)
    setattr(FixtureTableTests, 'test_' + pathlib.Path(_name).stem, _test)


class OriginalBugReportTests(SimpleTestCase):
    """The four bugs from the original report, on the layout that caused them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ocr, found = read_fixture('hospital_a.pdf')
        cls.values = {ef.patient_field: ef for ef in found.values}

    def test_text_layer_is_used_not_ocr(self):
        self.assertEqual(self.ocr.source, 'text_layer')

    def test_decimal_points_kept(self):
        self.assertEqual(self.values['potassium'].extracted_value, '4.1')
        self.assertEqual(self.values['rbc_count'].extracted_value, '4.41')

    def test_bilirubin_total_comes_from_its_own_row(self):
        total, direct = self.values['bilirubin_total'], self.values['bilirubin_direct']
        self.assertEqual((total.extracted_value, total.reference_range), ('0.8', '0.3–1.2 mg/dL'))
        self.assertEqual((direct.extracted_value, direct.reference_range), ('0.19', '0–0.2 mg/dL'))

    def test_ranges_read_beside_count_units(self):
        self.assertEqual(self.values['platelet_count'].reference_range, '150–400 10^3/uL')
        self.assertEqual(self.values['rbc_count'].reference_range, '3.8–4.8 *10^6/ul')
        self.assertEqual(self.values['potassium'].reference_range, '3.5–5.1 mmol/L')
        self.assertEqual(convert('platelet_count', '277.2', '10^3/uL').error, '')
        self.assertEqual(convert('rbc_count', '4.41', '*10^6/ul').error, '')

    def test_low_creatinine_is_a_clinical_flag_not_a_misread(self):
        creatinine = self.values['serum_creatinine']
        self.assertEqual(review.reference_flag(creatinine.extracted_value, creatinine.reference_range), 'low')
        self.assertEqual(creatinine.ocr_confidence, 100.0)
        self.assertFalse(_flagged_for_review(creatinine))


# ── Names ────────────────────────────────────────────────────────────────────

class TestNameTests(SimpleTestCase):
    def test_exact_aliases_only(self):
        cases = {
            'Bilirubin Total': 'bilirubin_total', 'Total Bilirubin': 'bilirubin_total', 'Bilirubin': 'bilirubin_total',
            'Bilirubin Direct': 'bilirubin_direct', 'Bilirubin (Direct)': 'bilirubin_direct',
            'Direct Bilirubin': 'bilirubin_direct', 'SGPT (ALT)': 'ssgpt_alt', 'S. Creatinine': 'serum_creatinine',
            'Creatinine (Jaffe Kinetic)': 'serum_creatinine', 'Haemoglobin (Hb)': 'hemoglobin',
            'Haematocrit (PCV)': 'hematocrit', 'Potassium (K+)': 'potassium', 'Sodium (Direct ISE)': 'sodium',
            'Total Leucocyte Count (TLC)': 'wbc_count', 'Glucose (Random)': 'blood_sugar_random',
            'Urea by Urease method': 'blood_urea', 'RBS (Random Blood Sugar)': 'blood_sugar_random',
        }
        for name, key in cases.items():
            self.assertEqual(match_test(name), key, name)

    def test_unknown_or_different_tests_are_not_guessed(self):
        for name in ('Bilirubin Indirect', 'Glucose', 'Glucose PP', 'Mean Cell Haemoglobin', 'Blood Urea Nitrogen',
                     'Haemoglobin Electrophoresis', 'Patient Name', '', '123'):
            self.assertIsNone(match_test(name), name)

    def test_no_alias_belongs_to_two_tests(self):
        self.assertGreater(len(alias_map()), 200)        # alias_map() raises on a duplicate

    def test_unmatched_names_are_logged(self):
        read = t.TableRead(t.PDF_COLUMNS, [t.Row('Vitamin D3', '28', 'ng/mL', '30 - 100')])
        with self.assertLogs('apps.lab_reports.services.table_reader', 'INFO') as logs:
            out = t.to_values(read, 'text_layer')
        self.assertEqual(out.values, [])
        self.assertEqual(out.unmatched[0]['name'], 'Vitamin D3')
        self.assertIn('Vitamin D3', logs.output[0])


# ── Cells: ranges, units, numbers ───────────────────────────────────────────

class CellTests(SimpleTestCase):
    def test_range_forms(self):
        cases = {'135 - 145': (135, 145), '3.5–5.1': (3.5, 5.1), '3.5 — 5.1': (3.5, 5.1), '3.5 -5.1': (3.5, 5.1),
                 '13 to 43': (13, 43), '0 - 0.2': (0, 0.2), '< 200': (None, 200), '<=5.6': (None, 5.6),
                 '> 40': (40, None), 'Up to 40': (None, 40), '4,000 - 11,000': (4000, 11000),
                 '1,50,000 - 4,50,000': (150000, 450000), '135-145 mmol/L': (135, 145)}
        for text, (low, high) in cases.items():
            ref, _rest = t.parse_range(text)
            self.assertEqual((ref.low, ref.high), (low, high), text)

    def test_ambiguous_or_missing_ranges_are_not_read(self):
        for text in ('M: 13 - 17  F: 12 - 15', '', 'See note', '17 - 13'):
            self.assertIsNone(t.parse_range(text)[0], text)

    def test_unit_spellings(self):
        cases = {'10^3/uL': '10^3/ul', '10^3/µL': '10^3/ul', 'x10³/µL': '10^3/ul', '10*3/cu.mm': '10^3/ul',
                 '*10^6/ul': '10^6/ul', '*10^6/UL': '10^6/ul', 'X 10^6 / uL': '10^6/ul', 'mill/cumm': '10^6/ul',
                 '10^9/L': '10^3/ul', '/cumm': '/ul', 'Lakhs/cumm': '10^5/ul', 'mmol/L': 'mmol/l',
                 '1043/uL': '10^3/ul', '10°3/uL': '10^3/ul', '“1046/ul': '10^6/ul'}
        for raw, key in cases.items():
            self.assertEqual(normalise_unit(raw), key, raw)

    def test_count_units_convert(self):
        self.assertEqual(convert('platelet_count', '2.5', 'lakhs/cumm').value, '250')
        self.assertEqual(convert('wbc_count', '7500', '/cumm').value, '7.5')
        self.assertEqual(convert('rbc_count', '4.41', 'mill/cumm').value, '4.41')
        self.assertTrue(convert('rbc_count', '4.41', 'g/dL').error)            # wrong unit: never guessed

    def test_result_cells(self):
        cases = {'4.1': '4.1', '0.5 L': '0.5', 'H 6.2': '6.2', '2,50,000': '250000', '13,13': '13.13',
                 '<0.5': '<0.5', '7,500': '7500', 'Positive': None, '': None}
        for text, want in cases.items():
            self.assertEqual(t.parse_number(text), want, text)

    def test_ocr_letters_in_number_cells(self):
        self.assertEqual(t.fix_ocr_digits('O-0.2'), '0-0.2')
        self.assertEqual(t.fix_ocr_digits('l3.2'), '13.2')
        self.assertEqual(t.fix_ocr_digits('mg/dL'), 'mg/dL')


# ── Table layouts from word positions ───────────────────────────────────────

def _words(lines):
    """[(y, [(x, text), ...]), ...] → word boxes (8 px per character, 10 px tall)."""
    return [(x, y, x + 8 * len(text), y + 10, text, None) for y, words in lines for x, text in words]


class LayoutTests(SimpleTestCase):
    def test_columns_found_from_header_synonyms_in_any_order(self):
        words = _words([
            (100, [(40, 'Investigation'), (250, 'Biological'), (340, 'Ref.'), (380, 'Interval'),
                   (470, 'Observed'), (540, 'Value'), (620, 'Units')]),
            (120, [(40, 'Potassium'), (250, '3.5'), (285, '-'), (300, '5.1'), (470, '4.1'), (620, 'mmol/L')]),
        ])
        rows, _cols = t.rows_from_words(words)
        self.assertEqual([(r.name, r.value, r.range, r.unit) for r in rows], [('Potassium', '4.1', '3.5 - 5.1', 'mmol/L')])

    def test_two_column_titles_next_to_each_other_are_not_one_phrase(self):
        line = _words([(100, [(40, 'Test'), (250, 'Result'), (330, 'Unit'), (430, 'Range')])])
        self.assertEqual(set(t.header_columns(line)), {'name', 'value', 'unit', 'range'})

    def test_a_sentence_is_not_a_header(self):
        line = _words([(100, [(40, 'The'), (72, 'result'), (128, 'value'), (176, 'was'), (208, 'checked'),
                              (272, 'twice'), (320, 'by'), (344, 'the'), (376, 'lab')])])
        self.assertIsNone(t.header_columns(line))

    def test_wrapped_names_and_section_titles(self):
        words = _words([
            (100, [(40, 'Test'), (250, 'Result'), (330, 'Unit'), (430, 'Reference'), (510, 'Range')]),
            (120, [(40, 'THYROID'), (110, 'PROFILE')]),
            (140, [(40, 'Thyroid'), (110, 'Stimulating'), (250, '2.5'), (330, 'mIU/L'), (430, '0.4-4.0')]),
            (152, [(40, 'Hormone')]),
            (172, [(40, 'Sodium'), (250, '137.4'), (330, 'mmol/L'), (430, '135-145')]),
        ])
        out = t.to_values(t.TableRead(t.PDF_COLUMNS, t.rows_from_words(words)[0]), 'text_layer')
        self.assertEqual({e.patient_field: e.extracted_value for e in out.values}, {'tsh': '2.5', 'sodium': '137.4'})
        self.assertEqual(out.unmatched, [])

    def test_long_name_spilling_into_the_result_column(self):
        words = _words([
            (100, [(40, 'Test'), (250, 'Result'), (330, 'Unit'), (430, 'Range')]),
            (120, [(40, 'Glucose'), (110, 'Random'), (230, '(Plasma)'), (262, '96.32'), (334, 'mg/dL'), (430, '70-140')]),
        ])
        rows, _ = t.rows_from_words(words)
        self.assertEqual((rows[0].name, rows[0].value), ('Glucose Random (Plasma)', '96.32'))


# ── Rows → values: conflicts, auto-fix, misreads ────────────────────────────

class RowValueTests(SimpleTestCase):
    def values(self, rows, source='text_layer'):
        return t.to_values(t.TableRead(t.PDF_COLUMNS, rows), source)

    def test_two_rows_read_as_one_test_is_a_conflict_not_an_overwrite(self):
        out = self.values([t.Row('Glucose Random', '110', 'mg/dL', '70-140'), t.Row('RBS', '150', 'mg/dL', '70-140')])
        self.assertEqual([e.extracted_value for e in out.values], ['110'])
        self.assertEqual([r['code'] for r in out.values[0].review_reasons], [review.CONFLICT])
        self.assertEqual(out.unmatched[0]['name'], 'RBS')

    def test_a_repeated_identical_row_is_not_a_conflict(self):
        out = self.values([t.Row('Sodium', '137.4', 'mmol/L', '135-145'), t.Row('Sodium', '137.4', 'mmol/L', '135-145')])
        self.assertEqual((len(out.values), out.values[0].review_reasons, out.unmatched), (1, [], []))

    def test_lost_decimal_point_is_auto_corrected_on_a_scan(self):
        out = self.values([t.Row('Potassium', '41', 'mmol/L', '3.5 - 5.1', confidence=91),
                           t.Row('RBC Count', '441', '10^6/uL', '3.8 - 4.8', confidence=93)], source='ocr')
        k, rbc = out.values
        self.assertEqual((k.extracted_value, k.suggested_value), ('41', '4.1'))
        self.assertEqual((rbc.extracted_value, rbc.suggested_value), ('441', '4.41'))
        self.assertEqual(k.review_reasons[0]['code'], review.DECIMAL_POINT)
        self.assertIn('Auto-corrected from 41 to 4.1', k.review_reasons[0]['message'])

    def test_auto_correction_without_a_range_needs_too_many_digits(self):
        """Without the row's range, as validator.decimal_suggestion: only a reading with more
        digits than any plausible value is corrected; "45" haemoglobin may be another misread."""
        self.assertEqual(t.decimal_fix('hemoglobin', '134', None, 'g/dL'), '13.4')
        self.assertEqual(t.decimal_fix('rbc_count', '441', None, '10^6/uL'), '4.41')
        self.assertIsNone(t.decimal_fix('hemoglobin', '45', None, 'g/dL'))
        self.assertIsNone(t.decimal_fix('blood_urea', '130', None, 'mg/dL'))            # 130 is possible
        self.assertIsNone(t.decimal_fix('potassium', '4', None, 'mmol/L'))

    def test_auto_correction_with_the_rows_range(self):
        ref = t.parse_range('3.5 - 5.1')[0]
        self.assertEqual(t.decimal_fix('potassium', '41', ref, 'mmol/L'), '4.1')
        self.assertIsNone(t.decimal_fix('potassium', '62', ref, 'mmol/L'))              # 6.2 is outside it too
        self.assertIsNone(t.decimal_fix('potassium', '4', ref, 'mmol/L'))

    def test_a_pdfs_own_text_is_never_auto_corrected(self):
        """Digits in a text layer are exact: a high urea of 130 must stay 130."""
        out = self.values([t.Row('Urea', '130', 'mg/dL', '13 - 43')], source='text_layer')
        self.assertEqual((out.values[0].suggested_value, out.values[0].review_reasons), ('', []))

    def test_a_misread_range_is_not_used(self):
        out = self.values([t.Row('Potassium', '41', 'mmol/L', '35 - 51', confidence=90)], source='ocr')
        k = out.values[0]
        self.assertEqual(k.reference_range, '')
        self.assertEqual([r['code'] for r in k.review_reasons], [review.RANGE_MISREAD])
        self.assertEqual(k.suggested_value, '')           # no usable range, and "41" is not too many digits
        self.assertTrue(_flagged_for_review(k))           # 41 is implausible: never saved without the user

    def test_missing_range_is_reported_not_replaced(self):
        out = self.values([t.Row('Haemoglobin', '12.6', 'g/dL', 'M: 13 - 17  F: 12 - 15')])
        self.assertEqual(out.values[0].reference_range, '')
        self.assertEqual(out.values[0].review_reasons, [])

    def test_out_of_range_alone_is_not_a_misread(self):
        self.assertEqual(review.reasons_for('0.5', 'mg/dL', 100.0, '0.6–1.1 mg/dL'), [])
        self.assertEqual(review.reference_flag('0.5', '0.6–1.1 mg/dL'), review.LOW)
        self.assertEqual(review.reference_flag('6.2', '3.5–5.1 mmol/L'), review.HIGH)
        self.assertIsNone(review.reference_flag('4.1', ''))

    def test_free_text_values_for_table_tests_must_be_confirmed(self):
        extracted = ExtractedReport(values=[
            ExtractedField('Bilirubin (Total)', 'bilirubin_total', '0.19'),
            ExtractedField('Blood Group', 'blood_group', 'O+'),
        ])
        t.merge_into(extracted, t.TableValues(t.TEXT_LINES, [], [{'name': 'X'}]))
        bili, group = extracted.values
        self.assertEqual([r['code'] for r in bili.review_reasons], [review.LOOSE_MATCH])
        self.assertEqual(group.review_reasons, [])          # not a table test
        self.assertEqual(extracted.unmatched_rows, [{'name': 'X'}])


# ── Through the API: preview, review screen, confirm ────────────────────────

@override_settings(SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class ReviewScreenTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        # The fixture reports' patient (see make_fixtures.py).
        self.patient = make_patient('test.patient', patient_id='PAT-0E2E0001', first_name='Test',
                                    last_name='Patient', gender='Female', dob='1992-01-01')
        self.client = APIClient()
        self.client.force_authenticate(self.patient.user)

    def upload_file(self, name):
        raw = (FIXTURES / name).read_bytes()
        return self.client.post('/api/v1/reports/upload/',
                                {'name': 'Lab report', 'file': SimpleUploadedFile(name, raw)}, format='multipart')

    def upload_text(self, text, n=[0]):
        n[0] += 1
        data = {'name': 'Lab report', 'file': SimpleUploadedFile('r.pdf', b'%PDF-1.4\n% table test ' + str(n[0]).encode())}
        with patch('apps.lab_reports.services.upload.read_document', return_value=OcrResult(text, 92.0)):
            return self.client.post('/api/v1/reports/upload/', data, format='multipart')

    def test_original_report_preview(self):
        r = self.upload_file('hospital_a.pdf')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'PENDING_CONFIRMATION')
        rows = {f['patient_field']: f for f in r.data['fields']}
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows['potassium']['converted_value'], '4.1')
        self.assertEqual(rows['rbc_count']['converted_value'], '4.41')
        self.assertEqual((rows['bilirubin_total']['converted_value'], rows['bilirubin_total']['reference_range']),
                         ('0.8', '0.3–1.2 mg/dL'))
        self.assertEqual(rows['bilirubin_direct']['converted_value'], '0.19')
        self.assertEqual(rows['platelet_count']['range_status'], 'read')
        self.assertEqual(rows['platelet_count']['reference_range'], '150–400 10^3/uL')
        creatinine = rows['serum_creatinine']
        self.assertEqual((creatinine['reference_flag'], creatinine['needs_confirmation'], creatinine['flag']),
                         ('low', False, ''))
        self.assertFalse(any(f['needs_confirmation'] for f in rows.values()))
        self.assertEqual(r.data['extracted']['unmatched_rows'], [])

    def test_unmatched_rows_are_shown_and_not_saved(self):
        r = self.upload_file('lab_b_investigation.pdf')
        self.assertEqual([u['name'] for u in r.data['extracted']['unmatched_rows']], ['Glucose PP'])
        self.assertNotIn('Glucose PP', [f['field_name'] for f in r.data['fields']])
        hb = next(f for f in r.data['fields'] if f['patient_field'] == 'hemoglobin')
        self.assertEqual((hb['reference_range'], hb['range_status'], hb['reference_flag']), ('', 'not_read', None))

    def test_auto_corrected_value_is_saved_only_after_confirmation(self):
        r = self.upload_text('Patient ID : PAT-0E2E0001\nPatient Name : Ms. Test Patient     Age/Sex : 34 Y / F\nReport Date : 14/09/2026\n'
                             'Potassium  41  mmol/L  3.5 - 5.1\nSodium  137.4  mmol/L  135 - 145')
        self.assertEqual(r.status_code, 201, r.data)
        k = next(f for f in r.data['fields'] if f['patient_field'] == 'potassium')
        self.assertEqual((k['extracted_value'], k['converted_value'], k['suggested_value']), ('41', '4.1', '4.1'))
        self.assertTrue(k['needs_confirmation'])
        self.assertEqual(k['confirmation_reasons'][0]['code'], 'decimal_point')
        self.assertIn('please confirm', k['confirmation_reasons'][0]['message'].lower())
        self.assertEqual(k['reference_flag'], 'normal')                 # judged on the corrected 4.1

        # A date change re-plans the preview: the correction must still need confirming.
        self.client.post(f"/api/v1/reports/{r.data['id']}/report-date/", {'report_date': '2026-09-15'}, format='json')
        field = LabReport.objects.get(pk=r.data['id']).fields.get(patient_field='potassium')
        self.assertTrue(field.needs_confirmation)
        self.assertEqual(field.suggested_value, '4.1')

        c = self.client.post(f"/api/v1/reports/{r.data['id']}/confirm/", {}, format='json')
        self.assertEqual(c.status_code, 200, c.data)
        self.assertFalse(LabResult.objects.filter(test_name='potassium').exists())     # not confirmed: not saved
        self.assertTrue(LabResult.objects.filter(test_name='sodium').exists())

    def test_confirmed_auto_correction_saves_the_corrected_value(self):
        r = self.upload_text('Patient ID : PAT-0E2E0001\nPatient Name : Ms. Test Patient     Age/Sex : 34 Y / F\nReport Date : 14/09/2026\n'
                             'Potassium  41  mmol/L  3.5 - 5.1')
        c = self.client.post(f"/api/v1/reports/{r.data['id']}/confirm/", {'confirmed': ['potassium']}, format='json')
        self.assertEqual(c.status_code, 200, c.data)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.potassium, Decimal('4.10'))

    def test_bilirubin_direct_is_saved_as_its_own_test(self):
        r = self.upload_file('hospital_a.pdf')
        c = self.client.post(f"/api/v1/reports/{r.data['id']}/confirm/", {}, format='json')
        self.assertEqual(c.status_code, 200, c.data)
        self.patient.refresh_from_db()
        self.assertEqual((self.patient.bilirubin_total, self.patient.bilirubin_direct), (Decimal('0.80'), Decimal('0.19')))


@skipUnless(tesseract_available(), 'Tesseract is not installed')
class ScannedReviewScreenTests(ReviewScreenTests):
    """The same report as an image-only PDF goes through OCR, with the same values."""

    def test_original_report_preview(self):
        r = self.upload_file('hospital_a_scanned.pdf')
        self.assertEqual(r.status_code, 201, r.data)
        rows = {f['patient_field']: f for f in r.data['fields']}
        self.assertEqual(rows['potassium']['converted_value'], '4.1')
        self.assertEqual(rows['rbc_count']['converted_value'], '4.41')
        self.assertEqual(rows['bilirubin_total']['reference_range'], '0.3–1.2 mg/dL')
        self.assertEqual(rows['platelet_count']['range_status'], 'read')
        self.assertEqual(rows['serum_creatinine']['reference_flag'], 'low')
        self.assertFalse(rows['serum_creatinine']['needs_confirmation'])

    # The inherited tests use the text-layer files; run them once, in ReviewScreenTests.
    test_unmatched_rows_are_shown_and_not_saved = None
    test_auto_corrected_value_is_saved_only_after_confirmation = None
    test_confirmed_auto_correction_saves_the_corrected_value = None
    test_bilirubin_direct_is_saved_as_its_own_test = None


# ── Per page: text layer or OCR ─────────────────────────────────────────────

class PageSourceTests(SimpleTestCase):
    """Each PDF page is read from its own text when it has real text, otherwise by OCR."""

    def test_print_to_pdf_outlines_have_no_text_layer_so_the_pages_are_ocrd(self):
        # "Microsoft Print to PDF" saves a web page's letters as vector outlines: they
        # render sharply, but get_text() finds nothing.
        pages = read_pdf_pages((FIXTURES / 'hospital_print_to_pdf.pdf').read_bytes())
        self.assertEqual([p.text for p in pages], ['', ''])
        self.assertFalse(any(p.has_text for p in pages))

    def test_scan_under_a_typed_letterhead_is_ocrd(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 40), 'SAMPLE LAB - typed letterhead, long enough to count as a text layer', fontsize=9)
        scan = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 100, 100), 0)
        scan.clear_with(255)
        page.insert_image(pymupdf.Rect(30, 60, 580, 800), pixmap=scan)
        p = read_pdf_pages(doc.tobytes())[0]
        self.assertTrue(has_text_layer(p.text))
        self.assertGreater(p.image_cover, 0.5)
        self.assertFalse(p.has_text)

    def test_a_short_typed_page_in_a_typed_report_is_not_ocrd(self):
        doc = pymupdf.open('pdf', (FIXTURES / 'hospital_a.pdf').read_bytes())
        doc.new_page().insert_text((40, 40), 'End of report')
        with patch('apps.lab_reports.ocr_service._ocr_images', side_effect=AssertionError('OCR was run')):
            result = read_document(doc.tobytes(), '.pdf')
        self.assertEqual(result.source, 'text_layer')
        self.assertEqual([p.source for p in result.pages], ['text_layer', 'text_layer'])


@skipUnless(tesseract_available(), 'Tesseract is not installed')
class ScannedAndMixedReportTests(SimpleTestCase):
    """The layout of the reported hospital report saved by "Print to PDF" (no text layer),
    and a PDF with one typed and one scanned page. (Image-only scans: the
    hospital_a_*scan* fixtures in expected_results.csv.)"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.printed_ocr, found = read_fixture('hospital_print_to_pdf.pdf')
        cls.printed = {ef.patient_field: ef for ef in found.values}
        cls.printed_unmatched = [u['name'] for u in found.unmatched]
        cls.mixed_ocr, found = read_fixture('mixed_text_and_scan.pdf')
        cls.mixed = {ef.patient_field: ef for ef in found.values}

    def test_expected_values_and_ranges_of_the_reported_layout(self):
        expected = {
            'sodium': ('137.4', '135–145'), 'potassium': ('4.1', '3.5–5.1'),
            'bilirubin_direct': ('0.19', '0–0.2'), 'bilirubin_total': ('0.8', '0.3–1.2'),
            'ssgpt_alt': ('18.89', '10–56'), 'blood_urea': ('13.81', '13–43'),
            'serum_creatinine': ('0.5', '0.6–1.1'), 'blood_sugar_random': ('96.32', '70–140'),
            'hemoglobin': ('13.13', '12–15'), 'hematocrit': ('38.5', '36–46'),
            'platelet_count': ('277.2', '150–400'), 'rbc_count': ('4.41', '3.8–4.8'),
        }
        self.assertEqual(self.printed_ocr.source, 'ocr')
        for key, (value, ref) in expected.items():
            ef = self.printed[key]
            with self.subTest(test=key):
                self.assertEqual(ef.suggested_value or ef.extracted_value, value)
                self.assertTrue(ef.reference_range.startswith(ref + ' '), ef.reference_range)

    def test_count_units_are_read_with_their_ranges(self):
        self.assertEqual(self.printed['platelet_count'].reference_range, '150–400 10^3/uL')
        self.assertEqual(self.printed['rbc_count'].reference_range, '3.8–4.8 10^6/uL')

    def test_low_creatinine_is_a_clinical_flag_not_a_low_confidence_misread(self):
        creatinine = self.printed['serum_creatinine']
        self.assertEqual(review.reference_flag(creatinine.extracted_value, creatinine.reference_range), 'low')
        self.assertFalse(_flagged_for_review(creatinine), creatinine.review_reasons)

    def test_patient_details_signatures_and_url_are_not_listed_as_tests(self):
        self.assertEqual(sorted(self.printed_unmatched), ['ALP', 'Lymphocyte', 'Neutrophil'])

    def test_mixed_pdf_reads_each_page_its_own_way(self):
        self.assertEqual(self.mixed_ocr.source, 'mixed')
        self.assertEqual([p.source for p in self.mixed_ocr.pages], ['text_layer', 'ocr'])
        self.assertEqual(self.mixed['potassium'].ocr_confidence, 100.0)            # typed page
        self.assertLess(self.mixed['tsh'].ocr_confidence, 100.0)                  # scanned page
        self.assertEqual(self.mixed['tsh'].extracted_value, '2.85')


# ── OCR misreads: units, names, stray rows, re-reading cells ────────────────

class OcrMisreadTests(SimpleTestCase):
    def test_garbled_power_of_ten_units(self):
        cases = {'10%3/uL': '10^3/ul', '*10�6/ul': '10^6/ul', "10'3/uL": '10^3/ul', '103/uL': '10^3/ul',
                 '*10°6/ul': '10^6/ul', 'ulU/mL': 'miu/l'}
        for raw, key in cases.items():
            self.assertEqual(normalise_unit(raw), key, raw)

    def test_a_garbled_unit_is_shown_in_the_tests_own_spelling(self):
        out = t.to_values(t.TableRead(t.OCR_COLUMNS, [
            t.Row('RBC Count', '4.41', '*10�6/ul', '3.8- 4.8', confidence=92, ocr=True),
            t.Row('Platelets Count', '277.2', '103/uL', '150- 400', confidence=94, ocr=True),
            t.Row('Haemoglobin', '13.13', 'g/dl', '12- 15', confidence=96, ocr=True),
        ]))
        self.assertEqual([(e.unit, e.reference_range) for e in out.values],
                         [('10^6/uL', '3.8–4.8 10^6/uL'), ('10^3/uL', '150–400 10^3/uL'), ('g/dl', '12–15 g/dl')])

    def test_names_joined_by_a_slash(self):
        self.assertEqual(match_test('Packed Cell Volume/ Haematocrit'), 'hematocrit')
        self.assertEqual(match_test('PCV/HCT'), 'hematocrit')
        self.assertEqual(match_test('Total Leukocytes Counts (Blood)'), 'wbc_count')
        self.assertIsNone(match_test('Sodium/Potassium'))                # two different tests: not guessed
        self.assertIsNone(match_test('Haematocrit/ Mean Cell Volume'))

    def test_lines_above_a_pages_own_header_are_not_rows(self):
        header = _words([(100, [(40, 'Examination'), (300, 'Result'), (380, 'Unit'), (460, 'Reference'),
                                (540, 'Range')])])
        _rows, columns = t.rows_from_words(header, 1)
        page2 = _words([
            (60, [(40, 'Sex:'), (80, 'Female'), (205, 'Reporting'), (285, 'Date:'), (330, '2026-07-26')]),
            (100, [(40, 'Examination'), (300, 'Result'), (380, 'Unit'), (460, 'Reference'), (540, 'Range')]),
            (120, [(40, 'Sodium'), (300, '137.4'), (380, 'mEq/L'), (460, '135-'), (500, '145')]),
        ])
        rows, _ = t.rows_from_words(page2, 2, columns)
        self.assertEqual([r.name for r in rows], ['Sodium'])

    def test_footer_lines_are_logged_but_not_listed_as_unknown_tests(self):
        read = t.TableRead(t.OCR_COLUMNS, [t.Row('MEDICAL LABORATORY NMC', '6240', '', 'TECHNOLOGIST'),
                                           t.Row('MPV', '8.24'), t.Row('Neutrophil', '82.21', '', '40-75%')])
        with self.assertLogs('apps.lab_reports.services.table_reader', 'INFO') as logs:
            out = t.to_values(read, 'ocr')
        self.assertEqual([u['name'] for u in out.unmatched], ['Neutrophil'])
        self.assertEqual(len(logs.output), 3)

    def _cell(self, value):
        return t.Row('RBC Count', value, '10^6/uL', '3.8-4.8', value_box=(0, 0, 10, 10), ocr=True, confidence=93)

    def test_an_enlarged_reading_that_disagrees_sends_the_value_to_review(self):
        row = self._cell('4.44')
        with patch('apps.lab_reports.ocr_service.ocr_numeric_cell', return_value=('4.41', 86.0)):
            t._check_enlarged(row, image=None)
        self.assertEqual(row.value, '4.44')
        self.assertEqual([n['code'] for n in row.notes], [review.READINGS_DIFFER])
        self.assertIn('4.44 / 4.41', row.notes[0]['message'])

    def test_an_enlarged_reading_that_shows_a_lost_decimal_point_is_used_but_confirmed(self):
        row = self._cell('441')
        with patch('apps.lab_reports.ocr_service.ocr_numeric_cell', return_value=('4.41', 92.0)):
            t._check_enlarged(row, image=None)
        self.assertEqual(row.value, '4.41')
        self.assertEqual([n['code'] for n in row.notes], [review.DECIMAL_POINT])
        ef = t.to_values(t.TableRead(t.OCR_COLUMNS, [row])).values[0]
        self.assertEqual(ef.suggested_value, '')                     # no second auto-fix on top
        self.assertTrue(_flagged_for_review(ef))

    def test_an_unsure_enlarged_reading_is_ignored(self):
        row = self._cell('277.2')
        with patch('apps.lab_reports.ocr_service.ocr_numeric_cell', return_value=('217.2', 51.0)):
            t._check_enlarged(row, image=None)
        self.assertEqual((row.value, row.notes), ('277.2', []))

    def _range_after_rereading(self, enlarged_range: str) -> str:
        row = t.Row('Potassium', '4.1', 'mEq/L', '3.5- 5.1', confidence=85, range_confidence=73,
                    value_box=(0, 0, 10, 10), range_box=(20, 0, 40, 10), ocr=True)

        def cell(_image, box, scale=1.0):
            if box == row.value_box:
                return '4.1', 95.0
            return ('3.5-5.1', 63.0) if scale == 1.0 else (enlarged_range, 20.0)

        with patch('apps.lab_reports.ocr_service.ocr_numeric_cell', side_effect=cell):
            t._reread_numeric([row], {1: object()})
        ef = t.to_values(t.TableRead(t.OCR_COLUMNS, [row])).values[0]
        self.assertEqual(ef.review_reasons, [])
        return ef.reference_range

    def test_a_range_read_the_same_three_times_is_used_even_when_scored_low(self):
        self.assertEqual(self._range_after_rereading('3.5-5.1'), '3.5–5.1 mEq/L')

    def test_two_agreeing_low_scored_range_readings_are_not_enough(self):
        # A 100 DPI scan read "0.6-1.1" as "0.6-1.4" twice; only the enlarged read failed.
        self.assertEqual(self._range_after_rereading(''), '')
        self.assertEqual(self._range_after_rereading('3.5-5.4'), '')

    def test_a_range_missed_by_the_page_read_is_looked_for_in_its_column(self):
        words = [(x, y, x + 8 * len(s), y + 10, s, 95.0) for y, line in [
            (100, [(40, 'Examination'), (300, 'Result'), (380, 'Unit'), (460, 'Reference'), (540, 'Range')]),
            (120, [(40, 'Total'), (90, 'Leukocytes'), (180, 'Counts'), (300, '11.27'), (380, '10^3/uL')]),
        ] for x, s in line]
        row = t.rows_from_words(words, 1)[0][0]
        self.assertEqual(row.range, '')
        x0, y0, x1, y1 = row.range_box
        self.assertEqual((y0, y1), (120, 130))                         # on this row ...
        self.assertTrue(380 + 8 * len('10^3/uL') <= x0 < 460 < x1)    # ... in the range column
