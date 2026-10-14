"""Tests for AHP-weighted TOPSIS doctor ranking: settings, criteria, query counts."""
from datetime import date, datetime, time

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.doctors.models import Doctor
from apps.recommendations.models import RankingSettings
from apps.recommendations.ranking import NO_SLOT_HOURS, free_hours_this_week, hours_to_earliest_slot, with_ranking_data
from apps.recommendations.smart_views import department_match, rank_doctors
from apps.recommendations.tests_smart import assign, doctor, prioritise
from apps.recommendations.views import build_recommendation
from apps.users.factories import make_admin, make_patient
from ml.ahp import CRITERIA, equal_matrix

URL = '/api/v1/ranking-settings/'
MONDAY = date(2026, 9, 28)
CIRCULAR = [[1, 9, 1 / 9, 1, 1], [1 / 9, 1, 9, 1, 1], [9, 1 / 9, 1, 1, 1], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1]]


def book(d, day, at, status='PENDING'):
    p = make_patient(f'{d.user.username}-{day}-{at}', phone=f'98{abs(hash((d.id, day, at))) % 10**8:08d}',
                     emergency=f'97{abs(hash((at, day, d.id))) % 10**8:08d}')
    return Appointment.objects.create(patient=p, doctor=d, appointment_date=day, appointment_time=at, status=status)


class RankingSettingsModelTests(TestCase):
    def test_default_is_all_equal_with_equal_weights(self):
        s = RankingSettings.load()
        self.assertEqual(s.ahp_pairwise, equal_matrix())
        self.assertEqual(set(s.ahp_weights), set(CRITERIA))
        for w in s.ahp_weights.values():
            self.assertAlmostEqual(w, 0.2)
        self.assertEqual(s.ahp_cr, 0.0)
        self.assertEqual(RankingSettings.load().pk, 1)            # one row only
        self.assertEqual(RankingSettings.objects.count(), 1)

    def test_saving_computes_weights_and_cr(self):
        prioritise(match=5, earliest_slot=3)
        s = RankingSettings.load()
        self.assertAlmostEqual(s.ahp_weights['match'], 5 / 11, places=4)
        self.assertAlmostEqual(s.ahp_weights['earliest_slot'], 3 / 11, places=4)
        self.assertAlmostEqual(sum(s.ahp_weights.values()), 1.0)
        self.assertLess(s.ahp_cr, 0.001)

    def test_bad_matrix_is_rejected_and_nothing_changes(self):
        RankingSettings.load()
        for bad, words in ((CIRCULAR, 'inconsistent'),
                           ([[1, 2], [0.5, 1]], '5x5'),
                           ([[1, 3, 1, 1, 1]] + equal_matrix()[1:], 'reciprocal'),
                           ([[0] * 5] * 5, 'positive'),
                           ('not a matrix', 'numbers')):
            s = RankingSettings(ahp_pairwise=bad)
            with self.assertRaises(ValidationError) as ctx:
                s.save()
            self.assertIn(words, str(ctx.exception.message_dict['ahp_pairwise']))
        self.assertEqual(RankingSettings.load().ahp_pairwise, equal_matrix())


@override_settings(SECURE_SSL_REDIRECT=False)
class RankingSettingsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(make_admin())

    def test_admin_reads_defaults(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['ahp_pairwise'], equal_matrix())
        self.assertEqual([c['key'] for c in r.data['criteria']], CRITERIA)
        self.assertEqual([c['benefit'] for c in r.data['criteria']], [False, True, False, True, True])

    def test_admin_saves_a_matrix_and_gets_weights_and_cr(self):
        m = equal_matrix()
        m[4][0], m[0][4] = 3, 1 / 3                              # match moderately over earliest slot
        r = self.client.put(URL, {'ahp_pairwise': m}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreater(r.data['ahp_weights']['match'], r.data['ahp_weights']['earliest_slot'])
        self.assertLess(r.data['ahp_cr'], 0.10)
        self.assertEqual(RankingSettings.load().ahp_pairwise, m)
        self.assertTrue(AuditLog.objects.filter(action='UPDATE_RANKING_SETTINGS').exists())

    def test_inconsistent_matrix_is_a_400(self):
        r = self.client.put(URL, {'ahp_pairwise': CIRCULAR}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('inconsistent', str(r.data['ahp_pairwise']))
        self.assertEqual(RankingSettings.load().ahp_pairwise, equal_matrix())
        self.assertEqual(self.client.put(URL, {}, format='json').status_code, 400)

    def test_only_admins(self):
        patient = make_patient('pat.nosy')
        client = APIClient()
        client.force_authenticate(patient.user)
        self.assertEqual(client.get(URL).status_code, 403)
        self.assertEqual(client.put(URL, {'ahp_pairwise': equal_matrix()}, format='json').status_code, 403)
        self.assertEqual(APIClient().get(URL).status_code, 401)


class CriteriaTests(TestCase):
    def test_earliest_slot_skips_booked_and_past_slots(self):
        d = doctor('dr.slot', 'Dermatology', schedule={'Monday': '09:00-17:00'})
        midnight = datetime.combine(MONDAY, time.min)
        self.assertEqual(hours_to_earliest_slot(d, midnight), 9.0)
        book(d, MONDAY, time(9, 10))                          # inside the 09:00 slot
        self.assertEqual(hours_to_earliest_slot(d, midnight), 9.5)
        self.assertEqual(hours_to_earliest_slot(d, datetime.combine(MONDAY, time(12))), 0.0)
        book(d, MONDAY, time(9, 30), status='CANCELLED')          # cancelled bookings free the slot
        self.assertEqual(hours_to_earliest_slot(d, midnight), 9.5)

    def test_no_free_slot_counts_the_whole_horizon(self):
        closed = doctor('dr.closed', 'Dermatology', schedule={}, first='Closed')
        self.assertEqual(hours_to_earliest_slot(closed, datetime.combine(MONDAY, time.min)), NO_SLOT_HOURS)
        full = doctor('dr.full', 'Dermatology', schedule={'Monday': '09:00-10:00'}, first='Full')
        for day in (MONDAY, date(2026, 10, 5)):                  # both Mondays in the 14 days
            book(full, day, time(9))
            book(full, day, time(9, 30))
        self.assertEqual(hours_to_earliest_slot(full, datetime.combine(MONDAY, time.min)), NO_SLOT_HOURS)
        later = doctor('dr.later', 'Dermatology', schedule={'Monday': '09:00-10:00'}, first='Later')
        ranked = rank_doctors([full, later], today=MONDAY)
        self.assertEqual(ranked[0]['id'], later.id)
        self.assertEqual(ranked[1]['earliest_slot_hours'], NO_SLOT_HOURS)

    def test_prefetched_free_hours_match_the_query(self):
        d = doctor('dr.week', 'Dermatology')
        book(d, MONDAY, time(10))
        loaded = with_ranking_data(Doctor.objects.filter(pk=d.pk), MONDAY).get()
        self.assertEqual(free_hours_this_week(loaded, MONDAY), free_hours_this_week(d, MONDAY))
        self.assertEqual(free_hours_this_week(loaded, MONDAY), 55.5)

    def test_non_primary_department_gets_the_model_share(self):
        derm = doctor('dr.derm', 'Dermatology', first='Derm')
        gp = doctor('dr.gp', 'General Medicine', first='Gp')
        heart = doctor('dr.heart', 'Cardiology', first='Heart')
        match = department_match('Dermatology', {'Dermatology': 0.8, 'General Medicine': 0.15})
        self.assertEqual(match, {'Dermatology': 1.0, 'General Medicine': 0.15})
        ranked = rank_doctors([heart, gp, derm], today=MONDAY, match=match)
        self.assertEqual([r['id'] for r in ranked], [derm.id, gp.id, heart.id])
        self.assertEqual([r['match'] for r in ranked], [1.0, 0.15, 0.0])

    def test_changing_the_matrix_changes_the_ranking(self):
        senior = doctor('dr.senior', 'Dermatology', first='Senior', experience_years=25)
        assign(senior, 4)
        junior = doctor('dr.junior', 'Dermatology', first='Junior', experience_years=1)
        prioritise(experience=9)
        self.assertEqual(rank_doctors([senior, junior], today=MONDAY)[0]['id'], senior.id)
        prioritise(caseload=9)
        self.assertEqual(rank_doctors([senior, junior], today=MONDAY)[0]['id'], junior.id)


# Fast hashing: these tests create over a hundred users.
@override_settings(SECURE_SSL_REDIRECT=False, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class QueryCountTests(TestCase):
    """Ranking runs a fixed number of queries however many doctors there are."""

    def add_doctors(self, start, stop, department):
        for i in range(start, stop):
            d = doctor(f'dr.q{department[:3]}{i}', department, first=f'Doc{i}', experience_years=i % 7)
            book(d, MONDAY, time(9 + i % 8))
            if i % 2:
                assign(d, 1)

    def queries(self, fn) -> int:
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx.captured_queries)

    def test_smart_ranker_is_constant_for_5_and_50_doctors(self):
        RankingSettings.load()

        def run():
            rank_doctors(list(with_ranking_data(Doctor.objects.filter(department='Dermatology'), MONDAY)),
                         today=MONDAY, match={'Dermatology': 1.0})

        self.add_doctors(0, 5, 'Dermatology')
        five = self.queries(run)
        self.add_doctors(5, 50, 'Dermatology')
        with self.assertNumQueries(five):
            run()

    def test_keyword_ranker_is_constant_for_5_and_50_doctors(self):
        RankingSettings.load()

        def run():
            build_recommendation('chest pain and palpitations', 5, 40, '')

        self.add_doctors(0, 5, 'Cardiology')
        five = self.queries(run)
        self.add_doctors(5, 50, 'Cardiology')
        with self.assertNumQueries(five):
            run()

    def test_keyword_checker_scores_with_topsis(self):
        self.add_doctors(0, 3, 'Cardiology')
        r = APIClient().post('/api/v1/recommendations/', {'symptoms': 'chest pain and palpitations',
                                                         'pain_level': 5, 'age': 40}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        for doc in r.data['ranked_doctors']:
            self.assertTrue(0 <= doc['score'] <= 1)
            self.assertIn('symptoms match Cardiology', doc['reasons'])
