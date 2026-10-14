"""Plain-language wording and severity of activity flag reasons (no database)."""
from django.test import SimpleTestCase

from apps.audit.reason_text import SEVERITY_THRESHOLDS, describe, flag_severity, round_half_up, severity


def reason(feature, value, median, z=8.0):
    return {'feature': feature, 'value': value, 'median': median, 'z': z, 'text': 'old technical text'}


class DescribeTests(SimpleTestCase):
    def text(self, *args, role='PATIENT', **kwargs):
        return describe(reason(*args, **kwargs), role)['text']

    def test_examples(self):
        self.assertEqual(self.text('total_actions', 44, 5.5), '44 actions in total. Most patients did about 6.')
        self.assertEqual(self.text('failed_logins', 12, 0), '12 failed login attempts. Most patients had none.')
        self.assertEqual(self.text('off_hours_actions', 4, 0, role='DOCTOR'),
                         '4 actions at unusual hours (such as at night). Most doctors had none.')
        self.assertEqual(self.text('distinct_patients', 1, 0, role='DOCTOR'),
                         'Opened 1 patient record. Most doctors opened none.')
        self.assertEqual(self.text('active_days', 2, 1), 'Active on 2 different days. Most patients were active on 1.')

    def test_singular_and_plural(self):
        cases = {
            'total_actions': ('1 action in total.', '2 actions in total.'),
            'distinct_patients': ('Opened 1 patient record.', 'Opened 2 patient records.'),
            'failed_logins': ('1 failed login attempt.', '2 failed login attempts.'),
            'off_hours_actions': ('1 action at unusual hours', '2 actions at unusual hours'),
            'active_days': ('Active on 1 day.', 'Active on 2 different days.'),
            'access_requests': ('1 request to see patient records.', '2 requests to see patient records.'),
            'access_denied': ('1 access request declined.', '2 access requests declined.'),
        }
        for metric, (one, two) in cases.items():
            with self.subTest(metric):
                self.assertTrue(self.text(metric, 1, 0).startswith(one))
                self.assertTrue(self.text(metric, 2, 0).startswith(two))
        self.assertTrue(self.text('total_actions', 0, 5).startswith('0 actions'))

    def test_median_zero_vs_non_zero(self):
        self.assertTrue(self.text('failed_logins', 9, 0).endswith('Most patients had none.'))
        self.assertTrue(self.text('failed_logins', 9, 2).endswith('Most patients had 2.'))
        self.assertTrue(self.text('distinct_patients', 9, 0, role='DOCTOR').endswith('Most doctors opened none.'))
        self.assertTrue(self.text('distinct_patients', 90, 9, role='DOCTOR').endswith('Most doctors opened 9.'))
        self.assertTrue(self.text('access_denied', 5, 0, role='ADMIN').endswith('Most administrators had none.'))

    def test_decimal_medians_round_half_up_and_say_about(self):
        self.assertTrue(self.text('total_actions', 44, 5.5).endswith('did about 6.'))
        self.assertTrue(self.text('total_actions', 44, 4.5).endswith('did about 5.'))   # round() would give 4
        self.assertTrue(self.text('total_actions', 44, 0.5).endswith('did about 1.'))
        self.assertTrue(self.text('total_actions', 44, 6.0).endswith('did 6.'))
        self.assertEqual([round_half_up(x) for x in (0.4, 0.5, 2.5, 3.5)], [0, 1, 3, 4])

    def test_detail_keeps_the_numbers_and_text_does_not(self):
        out = describe(reason('total_actions', 44, 5.5, z=10.4), 'PATIENT')
        self.assertEqual(out['metric'], 'total_actions')
        self.assertEqual(out['detail'], 'total_actions = 44, role median 5.5, robust z +10.4')
        self.assertNotIn('robust', out['text'])
        self.assertNotIn('median', out['text'])

    def test_unknown_metric_or_missing_numbers_fall_back_to_stored_text(self):
        self.assertEqual(describe({'feature': 'new_metric', 'text': 'raw'}, 'DOCTOR'),
                         {'metric': 'new_metric', 'text': 'raw', 'detail': 'raw'})
        self.assertEqual(describe({'feature': 'total_actions', 'text': 'raw'}, 'DOCTOR')['text'], 'raw')

    def test_unknown_role_says_users(self):
        self.assertTrue(self.text('failed_logins', 3, 0, role='NURSE').endswith('Most users had none.'))


class SeverityTests(SimpleTestCase):
    def test_thresholds(self):
        high, medium = SEVERITY_THRESHOLDS['HIGH'], SEVERITY_THRESHOLDS['MEDIUM']
        self.assertEqual((high, medium), (6.0, 3.5))
        self.assertEqual(severity(high), 'HIGH')
        self.assertEqual(severity(high - 0.01), 'MEDIUM')
        self.assertEqual(severity(medium), 'MEDIUM')
        self.assertEqual(severity(medium - 0.01), 'LOW')
        self.assertEqual(severity(0), 'LOW')
        self.assertEqual(severity(-7), 'HIGH')            # far below typical counts too

    def test_flag_uses_its_strongest_reason(self):
        self.assertEqual(flag_severity([reason('active_days', 2, 1, z=1.3), reason('failed_logins', 12, 0, z=5.6)]),
                         'MEDIUM')
        self.assertEqual(flag_severity([reason('total_actions', 44, 5.5, z=10.4)]), 'HIGH')
        self.assertEqual(flag_severity([{'feature': 'x', 'text': 'old'}]), 'LOW')
        self.assertEqual(flag_severity([]), 'LOW')
