"""OCR accuracy: OpenCV preprocessing, per-value confidence, printed units and ranges,
the confirmation checks (low confidence, far outside the printed range, lost decimal
point) and that unconfirmed values are never saved. Synthetic data only."""
from unittest import skipIf
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, override_settings
from PIL import Image, ImageDraw, ImageFont

from apps.lab_reports import ocr_service
from apps.lab_reports.models import LabResult
from apps.lab_reports.services import review
from apps.lab_reports.services import validator as v
from apps.lab_reports.services.extractor import extract_report
from apps.lab_reports.services.ocr import OcrResult
from apps.lab_reports.tests_api import LabApiTestCase, report_text


def text_page(angle=0.0) -> Image.Image:
    """A white page with rows of report text, optionally tilted."""
    try:
        font = ImageFont.truetype('arial.ttf', 22)
    except OSError:
        font = ImageFont.load_default(size=22)
    page = Image.new('L', (1240, 1754), 255)
    draw = ImageDraw.Draw(page)
    for i in range(24):
        draw.text((80, 100 + i * 50), 'Haemoglobin   13.4   g/dL   13.0 - 17.0', fill=0, font=font)
    return page.rotate(angle, fillcolor=255) if angle else page


# ── Preprocessing ────────────────────────────────────────────────────────────

@skipIf(ocr_service.cv2 is None, 'OpenCV is not installed')
class PreprocessTests(SimpleTestCase):
    def test_output_is_black_and_white_and_enlarged(self):
        out = ocr_service.preprocess_image(Image.new('RGB', (600, 400), 'white'))
        self.assertEqual(out.mode, 'L')
        self.assertGreaterEqual(out.width, 1200)
        self.assertGreaterEqual(out.height, 1200)
        self.assertTrue(set(np.unique(np.array(out))) <= {0, 255})

    def test_upscale_follows_the_configured_width_and_limit(self):
        gray = np.full((1000, 1000), 255, np.uint8)
        with override_settings(LAB_OCR_TARGET_WIDTH=2500, LAB_OCR_MAX_UPSCALE=3.0):
            self.assertEqual(ocr_service._upscale(gray).shape[1], 2500)
        with override_settings(LAB_OCR_TARGET_WIDTH=5000, LAB_OCR_MAX_UPSCALE=2.0):
            self.assertEqual(ocr_service._upscale(gray).shape[1], 2000)
        big = np.full((3000, 2400), 255, np.uint8)
        self.assertEqual(ocr_service._upscale(big).shape, (3000, 2400))     # never shrunk

    def test_skew_is_measured_and_corrected(self):
        for tilt in (3, -6):
            angle = ocr_service.skew_angle(np.array(text_page(tilt)))
            self.assertAlmostEqual(angle, -tilt, delta=0.5)

    def test_level_and_blank_pages_are_not_rotated(self):
        self.assertEqual(ocr_service.skew_angle(np.array(text_page())), 0.0)
        self.assertEqual(ocr_service.skew_angle(np.full((800, 600), 255, np.uint8)), 0.0)

    def test_uneven_lighting_does_not_fake_a_tilt(self):
        page = np.array(text_page(), dtype=np.int16)
        shadow = np.tile(np.linspace(0, 110, page.shape[1]), (page.shape[0], 1)).astype(np.int16)
        self.assertEqual(ocr_service.skew_angle(np.clip(page - shadow, 0, 255).astype(np.uint8)), 0.0)

    def test_deskew_can_be_turned_off(self):
        with override_settings(LAB_OCR_MAX_DESKEW_ANGLE=0):
            self.assertEqual(ocr_service.skew_angle(np.array(text_page(4))), 0.0)

    def test_pillow_fallback_without_opencv(self):
        with patch.object(ocr_service, 'cv2', None):
            out = ocr_service.preprocess_image(Image.new('RGB', (100, 100), 'white'))
        self.assertEqual((out.mode, out.width >= 1200), ('L', True))


class WordConfidenceTests(SimpleTestCase):
    def test_ocr_rows_keep_each_words_confidence(self):
        data = {'text': ['Haemoglobin', '13.4', 'g/dL', '', 'Platelets', '277'],
                'conf': [91, 62, 88, -1, 90, 95],
                'left': [10, 200, 300, 0, 10, 200], 'top': [10, 12, 11, 0, 60, 61],
                'width': [150, 50, 50, 0, 120, 40], 'height': [20, 20, 20, 0, 20, 20]}
        with patch.object(ocr_service.pytesseract, 'image_to_data', return_value=data):
            text, conf, lines = ocr_service._ocr_rows(Image.new('L', (10, 10)))
        self.assertEqual(text.splitlines()[0].split(), ['Haemoglobin', '13.4', 'g/dL'])
        self.assertEqual(lines, [[('Haemoglobin', 91.0), ('13.4', 62.0), ('g/dL', 88.0)],
                                 [('Platelets', 90.0), ('277', 95.0)]])
        self.assertEqual(conf, 85.2)

    def test_value_confidence_comes_from_the_value_after_its_label(self):
        words = [[('Haemoglobin', 90.0), ('13.0', 41.0), ('g/dL', 88.0), ('13.0-17.0', 70.0)],
                 [('RBS', 93.0), ('140', 96.0)]]
        self.assertEqual(review.value_confidence(words, '13.0', 'Haemoglobin 13.0 g/dL'), 41.0)
        self.assertEqual(review.value_confidence(words, '140', 'RBS 140'), 96.0)

    def test_value_on_the_line_below_its_label(self):
        words = [[('Haemoglobin', 90.0)], [('12.8', 58.0), ('g/dL', 80.0)]]
        self.assertEqual(review.value_confidence(words, '12.8', 'Haemoglobin'), 58.0)

    def test_blood_pressure_uses_the_lower_of_both_numbers(self):
        words = [[('BP', 92.0), ('120/', 88.0), ('80', 52.0), ('mmHg', 90.0)]]
        self.assertEqual(review.value_confidence(words, '120/80', 'BP'), 52.0)

    def test_ocr_misreads_inside_the_word_are_matched(self):
        words = [[('Glucose', 90.0), ('l4O', 66.0)]]
        self.assertEqual(review.value_confidence(words, '140', 'Glucose'), 66.0)

    def test_unknown_when_the_value_is_not_found_or_ambiguous(self):
        words = [[('A', 90.0), ('13.4', 60.0)], [('B', 90.0), ('13.4', 99.0)]]
        self.assertIsNone(review.value_confidence(words, '13.4', 'Haemoglobin'))
        self.assertIsNone(review.value_confidence(words, '99', 'Haemoglobin'))
        self.assertIsNone(review.value_confidence([], '13.4', 'Haemoglobin'))

    def test_attach_confidences_by_source(self):
        text = 'Haemoglobin 13.4 g/dL\nRBS 140 mg/dL'
        values = extract_report(text).values
        review.attach_confidences(values, OcrResult(text, 100.0, source='text_layer'))
        self.assertEqual({x.ocr_confidence for x in values}, {100.0})
        words = [[('Haemoglobin', 90.0), ('13.4', 44.0)], [('RBS', 90.0), ('l40', 97.0)]]
        review.attach_confidences(values, OcrResult(text, 80.0, source='ocr', words=words))
        self.assertEqual({x.patient_field: x.ocr_confidence for x in values},
                         {'hemoglobin': 44.0, 'blood_sugar_random': 97.0})
        review.attach_confidences(values, OcrResult(text, 80.0, source='ocr'))         # no word data
        self.assertEqual({x.ocr_confidence for x in values}, {80.0})


# ── Units and printed reference ranges ───────────────────────────────────────

class PrintedRangeTests(SimpleTestCase):
    def test_range_forms(self):
        cases = {
            ' g/dL 13.0 - 17.0': ('g/dL', 13.0, 17.0, '13–17 g/dL'),
            ' g/dL (13.0–17.0)': ('g/dL', 13.0, 17.0, '13–17 g/dL'),
            ' H 13.0-17.0 g/dL': ('g/dL', 13.0, 17.0, '13–17 g/dL'),
            ' mg/dL < 200': ('mg/dL', None, 200.0, '< 200 mg/dL'),
            ' mg/dL Up to 200': ('mg/dL', None, 200.0, '< 200 mg/dL'),
            ' mg/dL >40': ('mg/dL', 40.0, None, '> 40 mg/dL'),
            ' 70 to 140 mg/dL': ('mg/dL', 70.0, 140.0, '70–140 mg/dL'),
            ' mg/dL 1 70-140': ('mg/dL', 70.0, 140.0, '70–140 mg/dL'),        # "L" flag read as 1
        }
        for after, (unit, low, high, text) in cases.items():
            got_unit, ref = review.details_after_value(after)
            self.assertEqual((got_unit, ref.low, ref.high, ref.text), (unit, low, high, text), after)

    def test_no_range(self):
        for after in (' g/dL', '', ' g/dL Platelets 277 150-400', ' g/dL 17.0 - 13.0'):
            self.assertIsNone(review.details_after_value(after)[1], after)

    def test_stored_range_parsed_back(self):
        ref = review.parse_reference_range('13–17 g/dL')
        self.assertEqual((ref.low, ref.high, ref.unit), (13.0, 17.0, 'g/dL'))
        self.assertIsNone(review.parse_reference_range(''))

    def test_extraction_attaches_unit_and_range(self):
        report = extract_report('Haemoglobin 13.4 g/dL 13.0 - 17.0\n'
                                'Total Cholesterol 182 < 200 mg/dL\n'
                                'RBS 96 mg/dL\n')
        got = {x.patient_field: (x.unit, x.reference_range) for x in report.values}
        self.assertEqual(got['hemoglobin'], ('g/dL', '13–17 g/dL'))
        self.assertEqual(got['cholesterol_total'], ('mg/dL', '< 200 mg/dL'))   # unit printed after the range
        self.assertEqual(got['blood_sugar_random'], ('mg/dL', ''))


# ── The confirmation checks ──────────────────────────────────────────────────

class ConfirmationCheckTests(SimpleTestCase):
    def codes(self, *args, **kwargs):
        return [r['code'] for r in review.reasons_for(*args, **kwargs)]

    def test_nothing_to_confirm(self):
        self.assertEqual(self.codes('13.4', 'g/dL', 95.0, '13–17 g/dL'), [])
        self.assertEqual(self.codes('13.4', 'g/dL', None, ''), [])

    def test_low_confidence_uses_the_configured_threshold(self):
        self.assertEqual(self.codes('13.4', 'g/dL', 62.0, ''), [review.LOW_CONFIDENCE])
        with override_settings(LAB_VALUE_MIN_CONFIDENCE=50):
            self.assertEqual(self.codes('13.4', 'g/dL', 62.0, ''), [])

    def test_far_outside_the_printed_range(self):
        self.assertEqual(self.codes('560', 'mg/dL', 95.0, '70–140 mg/dL'), [review.FAR_OUTSIDE_RANGE])
        self.assertEqual(self.codes('300', 'mg/dL', 95.0, '70–140 mg/dL'), [])          # high, not far out
        self.assertEqual(self.codes('3', 'g/dL', 95.0, '13–17 g/dL'), [review.FAR_OUTSIDE_RANGE])
        with override_settings(LAB_FAR_OUTSIDE_FACTOR=5):
            self.assertEqual(self.codes('560', 'mg/dL', 95.0, '70–140 mg/dL'), [])

    def test_range_in_another_unit_is_not_compared(self):
        self.assertEqual(self.codes('560', 'mg/dL', 95.0, '3.9–7.8 mmol/L'), [])

    def test_decimal_suggestion_only_for_readings_with_too_many_digits(self):
        self.assertEqual(v.decimal_suggestion('cholesterol_total', '1302', 'mg/dL'), '130.2')
        self.assertEqual(v.decimal_suggestion('hemoglobin', '134', 'g/dL'), '13.4')
        self.assertEqual(v.decimal_suggestion('hemoglobin', '1340', 'g/dL'), '13.40')
        for field, raw in (('hemoglobin', '45'), ('cholesterol_total', '900'), ('triglycerides', '1500'),
                           ('hemoglobin', '13.4'), ('hemoglobin', '13'), ('blood_group', '134')):
            self.assertIsNone(v.decimal_suggestion(field, raw, 'g/dL'), (field, raw))

    def test_decimal_suggestion_prefers_the_printed_range(self):
        self.assertEqual(v.decimal_suggestion('blood_sugar_random', '4500', 'mg/dL'), '450.0')
        self.assertEqual(v.decimal_suggestion('blood_sugar_random', '4500', 'mg/dL', '30–60 mg/dL'), '45.00')

    def test_decimal_suggestion_makes_a_dropped_value_usable(self):
        self.assertTrue(v.is_usable('cholesterol_total', '1302', 'mg/dL'))
        self.assertFalse(v.is_usable('hemoglobin', '45', 'g/dL'))


# ── Preview → confirm ────────────────────────────────────────────────────────

class NeedsConfirmationApiTests(LabApiTestCase):
    def upload_words(self, text, words, confidence=90.0):
        with patch('apps.lab_reports.services.upload.read_document',
                   return_value=OcrResult(text, confidence, source='ocr', words=words)):
            return self.client.post('/api/v1/reports/upload/', {'name': 'Lab report', 'file': self.file()},
                                    format='multipart')

    def file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.lab_reports.tests_api import pdf_bytes
        return SimpleUploadedFile('report.pdf', pdf_bytes())

    def low_confidence_upload(self):
        text = report_text(self.patient, values=('Haemoglobin 13.4 g/dL 13.0 - 17.0', 'RBS 140 mg/dL 70 - 140'))
        words = [[('Haemoglobin', 92.0), ('13.4', 48.0), ('g/dL', 90.0)], [('RBS', 95.0), ('140', 96.0)]]
        r = self.upload_words(text, words)
        self.assertEqual(r.status_code, 201, r.data)
        return r

    def test_preview_shows_confidence_range_and_reasons(self):
        rows = self.rows(self.low_confidence_upload())
        hb, rbs = rows['hemoglobin'], rows['blood_sugar_random']
        self.assertEqual((hb['ocr_confidence'], hb['needs_confirmation'], hb['reference_range']),
                         (48.0, True, '13–17 g/dL'))
        self.assertEqual([r['code'] for r in hb['confirmation_reasons']], ['low_confidence'])
        self.assertIn('48%', hb['confirmation_reasons'][0]['message'])
        self.assertEqual((rbs['ocr_confidence'], rbs['needs_confirmation']), (96.0, False))
        self.assertEqual(LabResult.objects.count(), 0)                         # preview only

    def test_unconfirmed_value_is_never_saved(self):
        r = self.low_confidence_upload()
        c = self.confirm(r.data['id'])
        self.assertEqual(c.status_code, 200, c.data)
        hb = self.rows(c)['hemoglobin']
        self.assertEqual(hb['change_status'], 'SKIPPED')
        self.assertIn('not confirmed', hb['skip_reason'])
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.hemoglobin)
        self.assertEqual(str(self.patient.blood_sugar_random), '140.00')       # the confident value is saved
        self.assertFalse(LabResult.objects.filter(test_name='hemoglobin').exists())

    def test_confirmed_value_is_saved_and_audited(self):
        r = self.low_confidence_upload()
        c = self.confirm(r.data['id'], confirmed=['hemoglobin'])
        self.assertEqual(self.rows(c)['hemoglobin']['change_status'], 'INSERTED')
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '13.40')
        from apps.audit.models import AuditLog
        log = AuditLog.objects.filter(action='CONFIRM_LAB_REPORT').latest('id')
        self.assertIn('confirmed after review: hemoglobin', log.description)
        self.assertNotIn('13.4', log.description)                               # never values

    def test_a_corrected_value_counts_as_confirmed(self):
        r = self.low_confidence_upload()
        self.confirm(r.data['id'], values={'hemoglobin': '13.5'})
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.hemoglobin), '13.50')

    def test_text_layer_values_do_not_need_confirmation(self):
        text = report_text(self.patient, values=('Haemoglobin 13.4 g/dL',))
        with patch('apps.lab_reports.services.upload.read_document',
                   return_value=OcrResult(text, 100.0, source='text_layer')):
            r = self.client.post('/api/v1/reports/upload/', {'name': 'x', 'file': self.file()}, format='multipart')
        hb = self.rows(r)['hemoglobin']
        self.assertEqual((hb['ocr_confidence'], hb['needs_confirmation']), (100.0, False))

    def test_lost_decimal_point_is_suggested_and_needs_confirmation(self):
        r = self.upload(report_text(self.patient, values=('Total Cholesterol 1302 mg/dL', 'RBS 140 mg/dL')))
        self.assertEqual(r.status_code, 201, r.data)
        chol = self.rows(r)['cholesterol_total']
        self.assertEqual((chol['extracted_value'], chol['suggested_value'], chol['converted_value']),
                         ('1302', '130.2', '130.2'))
        self.assertEqual((chol['needs_confirmation'], chol['flag']), (True, ''))
        self.assertEqual([x['code'] for x in chol['confirmation_reasons']], ['decimal_point'])

        c = self.confirm(r.data['id'])                                          # not confirmed
        self.assertEqual(self.rows(c)['cholesterol_total']['change_status'], 'SKIPPED')
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.cholesterol_total)

    def test_lost_decimal_point_saved_once_confirmed(self):
        r = self.upload(report_text(self.patient, values=('Total Cholesterol 1302 mg/dL',)))
        self.confirm(r.data['id'], confirmed=['cholesterol_total'])
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.cholesterol_total), '130.20')

    def test_only_a_lost_decimal_point_report_is_not_rejected(self):
        r = self.upload(report_text(self.patient, values=('Haemoglobin 134 g/dL',)))
        self.assertEqual((r.status_code, r.data['status']), (201, 'PENDING_CONFIRMATION'))

    def test_far_outside_the_printed_range_needs_confirmation(self):
        r = self.upload(report_text(self.patient, values=('RBS 560 mg/dL 70 - 140', 'Haemoglobin 13.4 g/dL')))
        rbs = self.rows(r)['blood_sugar_random']
        self.assertEqual((rbs['needs_confirmation'], rbs['reference_range']), (True, '70–140 mg/dL'))
        self.assertEqual([x['code'] for x in rbs['confirmation_reasons']], ['far_outside_range'])
        self.confirm(r.data['id'])
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.blood_sugar_random)
        self.assertEqual(str(self.patient.hemoglobin), '13.40')

    def test_report_date_change_keeps_the_confirmation_need(self):
        r = self.low_confidence_upload()
        d = self.client.post(f'/api/v1/reports/{r.data["id"]}/report-date/', {'report_date': '2026-09-15'},
                             format='json')
        self.assertEqual(d.status_code, 200, d.data)
        hb = self.rows(d)['hemoglobin']
        self.assertEqual((hb['ocr_confidence'], hb['needs_confirmation']), (48.0, True))
