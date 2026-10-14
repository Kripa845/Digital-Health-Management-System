"""Tests for apps/audit/activity_anomaly.py (pure pandas, no database)."""
from datetime import datetime, timedelta
from unittest import TestCase

import numpy as np
import pandas as pd

from apps.audit.activity_anomaly import (
    FEATURES, analyse, build_features, demo_features, detect, explain, kdist_percentiles, robust_z,
    suggest_min_samples,
)
from ml.dbscan_audit import core_mask, gap_eps, knee

START = datetime(2026, 9, 1, 9, 0)


def doctor_events(user_id, n_patients, n_actions=40, days=20, failed=0, off_hours=0):
    """n_actions views spread over `days` working days, cycling through n_patients patients."""
    rows = [
        {'user_id': user_id, 'role': 'DOCTOR', 'action': 'VIEW_PATIENT',
         'timestamp': START + timedelta(days=i % days, hours=i % 6), 'patient_id': 1000 + i % n_patients}
        for i in range(n_actions)
    ]
    rows += [{'user_id': user_id, 'role': 'DOCTOR', 'action': 'SCAN_QR',
              'timestamp': START + timedelta(hours=14 + i % 2), 'patient_id': 1000} for i in range(off_hours)]
    rows += [{'user_id': user_id, 'role': 'DOCTOR', 'action': 'LOGIN_FAILED',
              'timestamp': START, 'patient_id': None} for _ in range(failed)]
    return rows


def normal_population(n=20):
    rows = []
    for u in range(n):
        rows += doctor_events(u, n_patients=5 + u % 3, n_actions=40 + u % 3)
    return rows


class BuildFeaturesTests(TestCase):
    def test_counts_per_user(self):
        events = pd.DataFrame(doctor_events(7, n_patients=4, n_actions=10, days=5, failed=2, off_hours=3))
        requests = pd.DataFrame([{'user_id': 7, 'role': 'DOCTOR', 'status': 'DECLINED'},
                                 {'user_id': 7, 'role': 'DOCTOR', 'status': 'APPROVED'}])
        row = build_features(events, requests).loc[7]
        self.assertEqual(row['role'], 'DOCTOR')
        self.assertEqual(row['total_actions'], 13)          # failed logins are not actions
        self.assertEqual(row['distinct_patients'], 4)
        self.assertEqual(row['failed_logins'], 2)
        self.assertEqual(row['off_hours_actions'], 3)       # 23:00 and 00:00
        self.assertEqual(row['active_days'], 5)
        self.assertEqual(row['access_requests'], 2)
        self.assertEqual(row['access_denied'], 1)

    def test_off_hours_boundaries(self):
        times = [START.replace(hour=h, minute=m) for h, m in [(21, 59), (22, 0), (5, 59), (6, 0)]]
        events = pd.DataFrame([{'user_id': 1, 'role': 'ADMIN', 'action': 'LOGIN', 'timestamp': t,
                                'patient_id': None} for t in times])
        self.assertEqual(build_features(events, None).loc[1, 'off_hours_actions'], 2)

    def test_empty_events_do_not_crash(self):
        feats = build_features(pd.DataFrame(), pd.DataFrame())
        self.assertEqual(len(feats), 0)
        self.assertEqual(list(feats.columns), ['role', *FEATURES])
        self.assertTrue(detect(feats, 'DOCTOR', 1.0, 5).skipped)
        self.assertEqual(kdist_percentiles(feats, 'DOCTOR', 5), {})


class DetectTests(TestCase):
    def test_only_the_extreme_user_is_flagged_with_reason(self):
        events = pd.DataFrame(normal_population() + doctor_events(99, n_patients=40, n_actions=42))
        result = detect(build_features(events, None), 'DOCTOR', eps=1.0, min_samples=5)
        self.assertFalse(result.skipped)
        self.assertEqual([f['user_id'] for f in result.flags], [99])
        reasons = result.flags[0]['reasons']
        self.assertEqual(reasons[0]['feature'], 'distinct_patients')
        self.assertIn('distinct_patients', reasons[0]['text'])
        self.assertGreater(reasons[0]['z'], 3.5)

    def test_normal_population_has_no_flags(self):
        result = detect(build_features(pd.DataFrame(normal_population()), None), 'DOCTOR', 1.0, 5)
        self.assertEqual(result.flags, [])

    def test_too_few_users_is_skipped(self):
        feats = build_features(pd.DataFrame(normal_population(9)), None)
        result = detect(feats, 'DOCTOR', 1.0, 5)                 # needs 2 * 5 = 10
        self.assertTrue(result.skipped)
        self.assertEqual(result.flags, [])
        self.assertIn('Lower min_samples to 4', result.message)
        self.assertTrue(detect(build_features(pd.DataFrame(normal_population(11)), None), 'DOCTOR', 1.0, 6).skipped)
        five = detect(build_features(pd.DataFrame(normal_population(5)), None), 'DOCTOR', 1.0, 2)
        self.assertTrue(five.skipped)                              # never fewer than MIN_GROUP = 6
        self.assertNotIn('Lower', five.message)

    def test_small_real_sized_group_runs_with_suggested_parameters(self):
        # Seven doctors, as on a new system: six alike and one viewing far more patients.
        events = pd.DataFrame(normal_population(6) + doctor_events(99, n_patients=40, n_actions=42))
        feats = build_features(events, None)
        suggested = analyse(feats, 'DOCTOR', 1.0, 5)['suggested']
        self.assertEqual(suggested['min_samples'], 3)
        result = detect(feats, 'DOCTOR', suggested['eps'], suggested['min_samples'])
        self.assertFalse(result.skipped)
        self.assertEqual([f['user_id'] for f in result.flags], [99])

    def test_other_roles_are_not_mixed_in(self):
        events = pd.DataFrame(normal_population())
        self.assertTrue(detect(build_features(events, None), 'PATIENT', 1.0, 5).skipped)

    def test_zero_spread_feature_gives_no_error(self):
        # Nobody has failed logins or access requests, and everyone is identical.
        rows = []
        for u in range(12):
            rows += doctor_events(u, n_patients=5, n_actions=40)
        feats = build_features(pd.DataFrame(rows), None)
        result = detect(feats, 'DOCTOR', 1.0, 5)
        self.assertEqual(result.flags, [])
        self.assertTrue(all(abs(r['z']) == 0 for r in explain(feats, 0)))
        self.assertTrue((robust_z(pd.Series([3, 3, 3])) == 0).all())

    def test_robust_z_when_most_values_are_equal(self):
        z = robust_z(pd.Series([0] * 20 + [6]))                # MAD is 0: falls back to mean deviation
        self.assertEqual(z.iloc[0], 0)
        self.assertGreater(z.iloc[-1], 3.5)

    def test_kdist_percentiles(self):
        pct = kdist_percentiles(build_features(pd.DataFrame(normal_population()), None), 'DOCTOR', 5)
        self.assertEqual(list(pct), [50, 75, 90, 95, 99])
        self.assertTrue(all(v >= 0 for v in pct.values()))


class AnalyseTests(TestCase):
    def test_demo_outliers_found_with_every_step(self):
        result = analyse(demo_features(), 'DOCTOR', eps=2.0, min_samples=5)
        self.assertFalse(result['skipped'])
        noise = {u['user_id'] for u in result['users'] if u['kind'] == 'noise'}
        self.assertTrue({-41, -42, -43} <= noise)                       # the three planted outliers
        self.assertEqual(sum(result['counts'].values()), result['n_users'])
        self.assertEqual(result['kdist_sorted'], sorted(result['kdist_sorted']))
        self.assertIsNotNone(result['suggested_eps'])
        user = result['users'][0]
        self.assertEqual(set(user['raw']), set(FEATURES))
        self.assertAlmostEqual(user['log']['total_actions'], np.log1p(user['raw']['total_actions']), places=3)
        self.assertTrue(all(u['reasons'] for u in result['users'] if u['kind'] == 'noise'))
        self.assertTrue(all(not u['reasons'] for u in result['users'] if u['kind'] != 'noise'))

    def test_matches_detect(self):
        feats = demo_features()
        flagged = {f['user_id'] for f in detect(feats, 'DOCTOR', 2.0, 5).flags}
        noise = {u['user_id'] for u in analyse(feats, 'DOCTOR', 2.0, 5)['users'] if u['kind'] == 'noise'}
        self.assertEqual(flagged, noise)

    def test_too_few_users_still_shows_features(self):
        result = analyse(demo_features().iloc[:5], 'DOCTOR', 1.0, 5)
        self.assertTrue(result['skipped'])
        self.assertEqual(len(result['users']), 5)
        self.assertTrue(all(u['kind'] is None for u in result['users']))

    def test_empty_and_identical(self):
        self.assertEqual(analyse(build_features(None, None), 'DOCTOR', 1.0, 5)['users'], [])
        same = pd.DataFrame([{'role': 'DOCTOR', **{f: 3 for f in FEATURES}}] * 12)
        result = analyse(same, 'DOCTOR', 1.0, 5)
        self.assertEqual(result['counts']['noise'], 0)
        self.assertIsNone(result['suggested_eps'])

    def test_knee_and_core_mask(self):
        self.assertAlmostEqual(knee([0.1, 0.1, 0.2, 0.2, 0.3, 3.0]), 0.3)
        self.assertIsNone(knee([1, 1, 1]))
        mask = core_mask([[0], [0.1], [0.2], [5]], eps=0.5, min_samples=3)
        self.assertEqual(mask.tolist(), [True, True, True, False])

    def test_gap_eps_sits_just_above_the_ordinary_users(self):
        curve = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 4.2, 5.0]
        self.assertAlmostEqual(gap_eps(curve), 1.5)               # 10% into the 1.2 -> 4.2 jump
        self.assertIsNone(gap_eps([1, 1, 1, 1]))
        self.assertIsNone(gap_eps([1, 2]))
        # A jump in the bottom half is ignored: at most half the users can be above eps.
        self.assertAlmostEqual(gap_eps([0, 3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.9]), 3.54)

    def test_suggested_min_samples(self):
        self.assertEqual([suggest_min_samples(n) for n in (6, 10, 15, 22, 43, 400)], [3, 3, 4, 5, 7, 20])

    def test_suggested_parameters_find_the_planted_outliers(self):
        suggested = analyse(demo_features(), 'DOCTOR', eps=1.0, min_samples=5)['suggested']
        self.assertEqual(suggested['min_samples'], 7)
        result = analyse(demo_features(), 'DOCTOR', suggested['eps'], suggested['min_samples'])
        self.assertEqual({u['user_id'] for u in result['users'] if u['kind'] == 'noise'}, {-41, -42, -43})
