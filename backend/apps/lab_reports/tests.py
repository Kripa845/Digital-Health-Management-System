from django.test import TestCase
from unittest.mock import patch, MagicMock
import io

from apps.lab_reports.extractor import (
    extract_medical_fields,
    normalize_ocr_text,
    validate_blood_pressure,
    validate_numeric_result,
)
from apps.lab_reports.ocr_service import preprocess_image


# ── Normalization tests ──────────────────────────────────────────────────────

class NormalizeOcrTextTests(TestCase):
    def test_line_breaks_normalized(self):
        text = "Line 1\r\nLine 2\rLine 3\n\n\nLine 4"
        result = normalize_ocr_text(text)
        self.assertIn('\n', result)
        self.assertNotIn('\r', result)

    def test_excessive_whitespace_collapsed(self):
        text = "Blood   Pressure     118/76    mmHg"
        result = normalize_ocr_text(text)
        self.assertEqual(result, "Blood Pressure 118/76 mmHg")

    def test_pipes_and_underscores_removed(self):
        text = "Hemoglobin|13.2_g/dL"
        result = normalize_ocr_text(text)
        self.assertEqual(result, "Hemoglobin 13.2 g/dL")

    def test_preserves_useful_structure(self):
        text = "Test: Result\n---\nValue"
        result = normalize_ocr_text(text)
        self.assertIn('Test: Result', result)
        self.assertIn('Value', result)


# ── Validation tests ─────────────────────────────────────────────────────────

class ValidationTests(TestCase):
    def test_valid_blood_pressure(self):
        self.assertTrue(validate_blood_pressure("120/80"))
        self.assertTrue(validate_blood_pressure("118/76"))

    def test_invalid_blood_pressure(self):
        self.assertFalse(validate_blood_pressure("300/200"))
        self.assertFalse(validate_blood_pressure("40/20"))
        self.assertFalse(validate_blood_pressure("abc/def"))

    def test_valid_numeric(self):
        self.assertTrue(validate_numeric_result("13.2", "hemoglobin"))
        self.assertTrue(validate_numeric_result("118/76", "blood_pressure"))

    def test_invalid_numeric(self):
        self.assertFalse(validate_numeric_result("abc", "hemoglobin"))
        self.assertFalse(validate_numeric_result("3000", "hemoglobin"))


# ── Extraction format tests ───────────────────────────────────────────────────

class ExtractionFormatATests(TestCase):
    """Blood Pressure: 118/76
       Hemoglobin: 13.2"""

    def test_colon_separated(self):
        text = "Blood Pressure: 118/76 mmHg\nHemoglobin: 13.2 g/dL"
        results = extract_medical_fields(text)
        bp = next((r for r in results if r.patient_field == 'blood_pressure'), None)
        hb = next((r for r in results if r.patient_field == 'hemoglobin'), None)
        self.assertIsNotNone(bp)
        self.assertEqual(bp.extracted_value, '118/76')
        self.assertIsNotNone(hb)
        self.assertEqual(hb.extracted_value, '13.2')


class ExtractionFormatBTests(TestCase):
    """Table-like spacing"""

    def test_table_spacing(self):
        text = (
            "Test                  Result       Unit\n"
            "-----------------------------------------\n"
            "Hemoglobin            13.2         g/dL\n"
            "Fasting Glucose        96           mg/dL\n"
            "Total Cholesterol      180          mg/dL\n"
        )
        results = extract_medical_fields(text)
        fields = {r.patient_field: r for r in results}
        self.assertIn('hemoglobin', fields)
        self.assertEqual(fields['hemoglobin'].extracted_value, '13.2')
        self.assertIn('blood_sugar_fasting', fields)
        self.assertEqual(fields['blood_sugar_fasting'].extracted_value, '96')
        self.assertIn('cholesterol_total', fields)
        self.assertEqual(fields['cholesterol_total'].extracted_value, '180')


class ExtractionFormatCTests(TestCase):
    """Values on next line"""

    def test_value_on_next_line(self):
        text = "Blood Pressure\n118/76\nmmHg"
        results = extract_medical_fields(text)
        bp = next((r for r in results if r.patient_field == 'blood_pressure'), None)
        self.assertIsNotNone(bp)
        self.assertEqual(bp.extracted_value, '118/76')


class ExtractionFormatDTests(TestCase):
    """Abbreviations"""

    def test_abbreviations(self):
        text = "BP 118/76\nHb 13.2\nFBS 92\nHDL 54\nLDL 96\nTG 150"
        results = extract_medical_fields(text)
        fields = {r.patient_field: r for r in results}
        self.assertIn('blood_pressure', fields)
        self.assertEqual(fields['blood_pressure'].extracted_value, '118/76')
        self.assertIn('hemoglobin', fields)
        self.assertEqual(fields['hemoglobin'].extracted_value, '13.2')
        self.assertIn('blood_sugar_fasting', fields)
        self.assertEqual(fields['blood_sugar_fasting'].extracted_value, '92')
        self.assertIn('cholesterol_hdl', fields)
        self.assertEqual(fields['cholesterol_hdl'].extracted_value, '54')
        self.assertIn('cholesterol_ldl', fields)
        self.assertEqual(fields['cholesterol_ldl'].extracted_value, '96')
        self.assertIn('triglycerides', fields)
        self.assertEqual(fields['triglycerides'].extracted_value, '150')


class ExtractionFormatETests(TestCase):
    """Mixed formats with units"""

    def test_mixed_units(self):
        text = (
            "Fasting Blood Sugar: 92 mg/dL\n"
            "Random Blood Sugar: 140 mg/dL\n"
            "Total Cholesterol: 210 mg/dL\n"
            "HDL Cholesterol: 45 mg/dL\n"
            "LDL Cholesterol: 130 mg/dL\n"
            "Triglycerides: 160 mg/dL\n"
        )
        results = extract_medical_fields(text)
        fields = {r.patient_field: r for r in results}
        self.assertEqual(fields['blood_sugar_fasting'].extracted_value, '92')
        self.assertEqual(fields['blood_sugar_random'].extracted_value, '140')
        self.assertEqual(fields['cholesterol_total'].extracted_value, '210')
        self.assertEqual(fields['cholesterol_hdl'].extracted_value, '45')
        self.assertEqual(fields['cholesterol_ldl'].extracted_value, '130')
        self.assertEqual(fields['triglycerides'].extracted_value, '160')


class ExtractionMultiFieldTests(TestCase):
    """All supported fields from one report"""

    def test_full_lipid_panel_and_vitals(self):
        text = (
            "Blood Pressure: 118/76 mmHg\n"
            "Pulse: 72 bpm\n"
            "Temperature: 36.8 C\n"
            "Hemoglobin: 13.4 g/dL\n"
            "Fasting Glucose: 92 mg/dL\n"
            "Random Glucose: 140 mg/dL\n"
            "Total Cholesterol: 210 mg/dL\n"
            "HDL: 45 mg/dL\n"
            "LDL: 130 mg/dL\n"
            "Triglycerides: 160 mg/dL\n"
            "Height: 170 cm\n"
            "Weight: 70 kg\n"
        )
        results = extract_medical_fields(text)
        fields = {r.patient_field: r for r in results}
        self.assertEqual(fields['blood_pressure'].extracted_value, '118/76')
        self.assertEqual(fields['hemoglobin'].extracted_value, '13.4')
        self.assertEqual(fields['blood_sugar_fasting'].extracted_value, '92')
        self.assertEqual(fields['blood_sugar_random'].extracted_value, '140')
        self.assertEqual(fields['cholesterol_total'].extracted_value, '210')
        self.assertEqual(fields['cholesterol_hdl'].extracted_value, '45')
        self.assertEqual(fields['cholesterol_ldl'].extracted_value, '130')
        self.assertEqual(fields['triglycerides'].extracted_value, '160')
        self.assertEqual(fields['height'].extracted_value, '170')
        self.assertEqual(fields['weight'].extracted_value, '70')


class ExtractionReferenceRangeTests(TestCase):
    """Reference ranges must not be saved as patient values"""

    def test_reference_range_not_extracted_as_value(self):
        text = (
            "Hemoglobin        13.4        g/dL       12-16\n"
            "Fasting Glucose    95         mg/dL       70-100\n"
        )
        results = extract_medical_fields(text)
        fields = {r.patient_field: r for r in results}
        self.assertEqual(fields['hemoglobin'].extracted_value, '13.4')
        self.assertEqual(fields['blood_sugar_fasting'].extracted_value, '95')
        for r in results:
            self.assertNotIn('-', r.extracted_value)
            self.assertNotIn('to', r.extracted_value.lower())


class ExtractionEmptyTests(TestCase):
    def test_empty_text(self):
        results = extract_medical_fields('')
        self.assertEqual(results, [])

    def test_no_valid_fields(self):
        text = "This is just a random letter with no numbers."
        results = extract_medical_fields(text)
        self.assertEqual(results, [])


# ── Preprocessing tests ───────────────────────────────────────────────────────

class PreprocessingTests(TestCase):
    def test_preprocess_returns_image(self):
        from PIL import Image
        img = Image.new('RGB', (100, 100), color='white')
        processed = preprocess_image(img)
        self.assertIsInstance(processed, Image.Image)
        self.assertEqual(processed.mode, 'L')

    def test_preprocess_upscales_small_image(self):
        from PIL import Image
        img = Image.new('RGB', (100, 100), color='white')
        processed = preprocess_image(img)
        self.assertGreaterEqual(processed.width, 1200)
        self.assertGreaterEqual(processed.height, 1200)


# ── False-positive and record-safety tests ────────────────────────────────────

class ExtractionFalsePositiveTests(TestCase):
    def _fields(self, text):
        return {r.patient_field: r for r in extract_medical_fields(text)}

    def test_short_aliases_do_not_match_inside_words(self):
        self.assertEqual(self._fields('Patient seen in the past 3 months. Salt 5 g/day.'), {})

    def test_generic_words_are_not_blood_group(self):
        self.assertNotIn('blood_group', self._fields('Visit type: 2'))
        self.assertNotIn('blood_group', self._fields('Grade A+ student'))

    def test_blood_group_not_taken_from_neighbouring_number(self):
        fields = self._fields('Blood group: AB+  Hb 13.2 g/dL')
        self.assertEqual(fields['blood_group'].extracted_value, 'AB+')
        self.assertEqual(fields['hemoglobin'].extracted_value, '13.2')

    def test_value_belongs_to_its_own_label(self):
        fields = self._fields('SGPT: 34 U/L  SGOT: 28 U/L')
        self.assertEqual(fields['ssgpt_alt'].extracted_value, '34')
        self.assertEqual(fields['ssgot_ast'].extracted_value, '28')


class CDSASafetyTests(TestCase):
    def setUp(self):
        from apps.users.factories import make_patient
        from apps.lab_reports.models import LabReport
        self.patient = make_patient()
        self.report = LabReport.objects.create(patient=self.patient, name='r', file='lab_reports/r.pdf')

    def _run(self, text):
        from apps.lab_reports.cdsa import run_cdsa
        result = run_cdsa(self.report, extract_medical_fields(text))
        self.patient.refresh_from_db()
        return result

    def test_blood_group_is_never_changed_by_ocr(self):
        result = self._run('Blood group: AB+')
        self.assertEqual(self.patient.blood_group, 'O+')
        self.assertEqual([f.patient_field for f in result.needs_review_fields], ['blood_group'])

    def test_implausible_value_is_not_saved(self):
        result = self._run('Hemoglobin: 132 g/dL')
        self.assertIsNone(self.patient.hemoglobin)
        self.assertEqual(result.needs_review_count, 1)

    def test_value_too_large_for_column_is_not_saved(self):
        from apps.lab_reports.extractor import ExtractedField
        from apps.lab_reports.cdsa import run_cdsa
        run_cdsa(self.report, [ExtractedField('Bilirubin', 'bilirubin_total', '1234.5', confidence='high')])
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.bilirubin_total)

    def test_valid_value_is_saved(self):
        self._run('Hemoglobin: 13.2 g/dL')
        self.assertEqual(str(self.patient.hemoglobin), '13.20')
