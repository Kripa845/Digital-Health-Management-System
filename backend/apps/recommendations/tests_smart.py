"""Tests for the smart symptom check endpoint (Random Forest + TOPSIS)."""
from datetime import date, time
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.doctors.models import DoctorAssignment
from apps.recommendations.models import RankingSettings, RecommendationHistory
from apps.recommendations.smart_views import free_hours_this_week, rank_doctors
from apps.users.factories import make_doctor, make_patient
from ml import symptom_model
from ml.ahp import CRITERIA

URL = '/api/v1/smart-symptom-check/'
REFLUX = 'heartburn, worse after eating and worse lying down'   # -> Gastroenterology (GERD)
EVERY_DAY = {day: '09:00-17:00' for day in
             ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')}
DISCLAIMER = 'Suggestion only, not a medical diagnosis.'


def doctor(username, department, schedule=None, first='Asha', last='Rai', **extra):
    d = make_doctor(username, license_number=f'NMC-{abs(hash(username)) % 99999}', department=department,
                    availability_schedule=schedule if schedule is not None else EVERY_DAY, **extra)
    d.user.first_name, d.user.last_name = first, last
    d.user.save()
    return d


def assign(d, n):
    for i in range(n):
        p = make_patient(f'{d.user.username}-p{i}', phone=f'98{abs(hash((d.id, i))) % 10**8:08d}',
                         emergency=f'97{abs(hash((i, d.id))) % 10**8:08d}')
        DoctorAssignment.objects.create(doctor=d, patient=p, status='Active')


@override_settings(SECURE_SSL_REDIRECT=False)
class SmartSymptomCheckTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not symptom_model.load():
            raise AssertionError('Run "python -m ml.train_model" first: ml/symptom_model.joblib is missing.')

    def post(self, text, client=None):
        return (client or APIClient()).post(URL, {'text': text}, format='json')

    def test_ranks_department_doctors_with_topsis_and_saves_history(self):
        busy = doctor('dr.busy', 'Gastroenterology', first='Busy', last='Bista')
        free = doctor('dr.free', 'Gastroenterology', first='Free', last='Gurung')
        assign(busy, 3)
        r = self.post(REFLUX)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['status'], r.data['department']), ('ok', 'Gastroenterology'))
        self.assertEqual(r.data['disclaimer'], DISCLAIMER)
        self.assertEqual(len(r.data['illnesses']), 3)
        names = [d['name'] for d in r.data['doctors']]
        self.assertEqual(names, ['Free Gurung', 'Busy Bista'])          # same hours, lighter caseload wins
        self.assertIn('lightest caseload', r.data['doctors'][0]['reason'])
        self.assertGreater(r.data['doctors'][0]['score'], r.data['doctors'][1]['score'])
        h = RecommendationHistory.objects.get(id=r.data['history_id'])
        self.assertEqual((h.recommended_department, h.recommended_doctor_id, h.symptoms),
                         ('Gastroenterology', free.id, REFLUX))
        self.assertEqual(h.confidence, round(100 * r.data['dept_probability']))
        self.assertIn(DISCLAIMER, h.reason)
        self.assertIsNone(h.patient)                                    # guest

    def test_history_linked_to_logged_in_patient(self):
        doctor('dr.gut', 'Gastroenterology')
        patient = make_patient('pat.smart')
        client = APIClient()
        client.force_authenticate(patient.user)
        r = self.post(REFLUX, client)
        self.assertEqual(RecommendationHistory.objects.get(id=r.data['history_id']).patient, patient)

    def test_exactly_one_doctor(self):
        only = doctor('dr.only', 'Gastroenterology')
        r = self.post(REFLUX)
        self.assertEqual(len(r.data['doctors']), 1)
        self.assertEqual((r.data['doctors'][0]['id'], r.data['doctors'][0]['score']), (only.id, 1.0))
        self.assertEqual(r.data['doctors'][0]['reason'], 'only active doctor in this department')

    def test_no_doctor_in_department_falls_back_to_general_medicine(self):
        gp = doctor('dr.gp', 'General Medicine')
        r = self.post(REFLUX)
        self.assertEqual(r.data['department'], 'Gastroenterology')           # the suggestion is unchanged
        self.assertEqual(r.data['doctors_department'], 'General Medicine')
        self.assertEqual([d['id'] for d in r.data['doctors']], [gp.id])
        self.assertIn('No Gastroenterology doctor', r.data['doctors_note'])

    def test_no_doctors_at_all(self):
        r = self.post(REFLUX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['doctors'], r.data['doctors_department']), ([], None))
        self.assertIn('Please contact the hospital', r.data['doctors_note'])
        self.assertIsNone(RecommendationHistory.objects.get(id=r.data['history_id']).recommended_doctor)

    def test_inactive_doctors_are_not_suggested(self):
        doctor('dr.off', 'Gastroenterology', status='Inactive')
        self.assertEqual(self.post(REFLUX).data['doctors_department'], None)

    def test_top_three_only(self):
        for i in range(5):
            doctor(f'dr.d{i}', 'Gastroenterology', first=f'Doc{i}')
        self.assertEqual(len(self.post(REFLUX).data['doctors']), 3)

    def test_unsure_result_suggests_general_medicine_and_is_saved(self):
        gp = doctor('dr.gp', 'General Medicine', first='Gita', last='Pant')
        doctor('dr.cardio', 'Cardiology')
        for text, expected in (('I only have heartburn', 'not_enough_info'),
                               ('no heartburn, no cough', 'not_enough_info'),
                               ('dizziness and nausea', 'not_enough_info'),
                               ('fever, nausea and dizziness', 'low_confidence'),
                               ('rash, swelling, itching', 'low_confidence')):
            r = self.post(text)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data['status'], expected, text)
            self.assertEqual(r.data['disclaimer'], DISCLAIMER)
            self.assertEqual(r.data['department'], 'General Medicine')
            self.assertNotIn('illnesses', r.data)
            self.assertEqual([d['id'] for d in r.data['doctors']], [gp.id])
            h = RecommendationHistory.objects.get(id=r.data['history_id'])
            self.assertEqual((h.recommended_department, h.confidence), ('General Medicine', None))
        self.assertEqual(RecommendationHistory.objects.count(), 5)

    def test_unsure_spelling_asks_did_you_mean_first(self):
        r = self.post('feverr, cough and sore throat')
        self.assertEqual(r.data['status'], 'needs_confirmation')
        self.assertEqual(r.data['suggestions'],
                         [{'term': 'feverr', 'symptom': 'E_91', 'label': 'fever', 'score': 90.9}])
        self.assertNotIn('illnesses', r.data)
        yes = APIClient().post(URL, {'text': 'feverr, cough and sore throat', 'answers': {'E_91': True}},
                               format='json')
        self.assertIn('fever', yes.data['symptoms'])
        no = APIClient().post(URL, {'text': 'feverr, cough and sore throat', 'dismissed': ['feverr']},
                              format='json')
        self.assertNotIn('fever', no.data['symptoms'])
        self.assertEqual(APIClient().post(URL, {'text': 'feverr', 'dismissed': 'feverr'},
                                          format='json').status_code, 400)

    def test_unrecognised_warning_sign_still_returns_emergency(self):
        r = self.post('rash, itching and my throat is closing')
        self.assertEqual(r.data['status'], 'emergency')
        self.assertEqual([f['id'] for f in r.data['red_flags']], ['throat_swelling'])

    def test_red_flag_returns_emergency_and_is_not_saved(self):
        r = self.post('cough and coughing up blood')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['status'], r.data['department']), ('emergency', 'Emergency Medicine'))
        self.assertEqual([f['id'] for f in r.data['red_flags']], ['coughing_up_blood'])
        self.assertNotIn('illnesses', r.data)
        self.assertEqual(RecommendationHistory.objects.count(), 0)

    def test_unsure_result_asks_a_question_and_accepts_the_answer(self):
        r = self.post('dizziness and nausea')
        question = r.data['question']
        self.assertEqual(set(question), {'symptom', 'label', 'text'})
        r2 = APIClient().post(URL, {'text': 'dizziness and nausea', 'answers': {question['symptom']: True}},
                              format='json')
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertIn(question['label'], r2.data['symptoms'])

    def test_bad_answers_rejected(self):
        for answers in ({'E_99999': True}, {'E_91': 'yes'}, ['E_91']):
            r = APIClient().post(URL, {'text': 'fever and cough', 'answers': answers}, format='json')
            self.assertEqual(r.status_code, 400, answers)

    def test_response_shows_how_terms_were_understood(self):
        r = self.post('heartburn, worse after eating, worse lying down, no fever, blorf')
        self.assertEqual(r.data['status'], 'ok')
        self.assertIn({'term': 'heartburn', 'symptom': 'heartburn', 'method': 'exact', 'score': None},
                      r.data['matched'])
        self.assertEqual(r.data['negated'], ['fever'])
        self.assertEqual(r.data['unrecognized'], ['blorf'])

    def test_synonyms_and_typos_reach_the_model(self):
        r = self.post('heartbrn and worse aftr eating')
        methods = {m['symptom']: m['method'] for m in r.data['matched']}
        self.assertEqual(methods, {'heartburn': 'fuzzy', 'worse after eating': 'fuzzy'})
        self.assertEqual(sorted(r.data['symptoms']), ['heartburn', 'worse after eating'])

    def test_not_ok_status_still_lists_unrecognized_terms(self):
        r = self.post('asdfgh qwerty')
        self.assertEqual(r.data['status'], 'not_enough_info')
        self.assertEqual((r.data['matched'], r.data['unrecognized']), ([], ['asdfgh qwerty']))

    def test_empty_and_very_long_text_rejected(self):
        for text in ('', '   '):
            self.assertEqual(self.post(text).status_code, 400)
        r = self.post('heartburn ' * 400)                                  # 3200 characters
        self.assertEqual(r.status_code, 400)
        self.assertIn('2000', r.data['detail'])
        self.assertEqual(APIClient().post(URL, {'text': 123}, format='json').status_code, 400)

    def test_keyword_checker_still_works(self):
        r = APIClient().post('/api/v1/recommendations/', {'symptoms': 'chest pain and palpitations',
                                                         'pain_level': 5, 'age': 40}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['recommended_department'], 'Cardiology')


class FreeHoursTests(TestCase):
    def test_hours_from_today_to_sunday_minus_open_bookings(self):
        d = doctor('dr.hours', 'Dermatology', schedule={
            'Monday': '09:00-17:00', 'Tuesday': 'closed', 'Wednesday': '10:00-14:00', 'Thursday': '',
            'Friday': 'bad value', 'Saturday': '09:00-12:00', 'Sunday': 'closed'})
        wednesday = date(2026, 9, 30)                       # Wed..Sun: 4 + 0 + 0 + 3 + 0 = 7 hours
        self.assertEqual(free_hours_this_week(d, today=wednesday), 7.0)
        p = make_patient('pat.booked')
        for i, st in enumerate(('PENDING', 'ACCEPTED', 'CANCELLED', 'DECLINED')):
            Appointment.objects.create(patient=p, doctor=d, appointment_date=wednesday,
                                       appointment_time=time(10 + i), status=st)
        Appointment.objects.create(patient=p, doctor=d, appointment_date=date(2026, 10, 5),  # next week
                                   appointment_time=time(10), status='PENDING')
        self.assertEqual(free_hours_this_week(d, today=wednesday), 6.0)   # 2 open bookings x 0.5 h

    def test_monday_counts_the_whole_week(self):
        d = doctor('dr.week', 'Dermatology')
        self.assertEqual(free_hours_this_week(d, today=date(2026, 9, 28)), 56.0)   # 7 days x 8 h

    def test_more_free_hours_wins_when_caseload_is_equal(self):
        part = doctor('dr.part', 'Dermatology', schedule={'Monday': '09:00-11:00'}, first='Part')
        full = doctor('dr.full', 'Dermatology', first='Full')
        ranked = rank_doctors([part, full], today=timezone.localdate())
        self.assertEqual(ranked[0]['id'], full.id)
        self.assertIn('most free hours', ranked[0]['reason'])


@override_settings(SECURE_SSL_REDIRECT=False)
class SmartCheckForPatientTests(TestCase):
    """An admin can run the check for an existing patient; a patient always checks for themselves."""

    def setUp(self):
        from apps.users.factories import make_admin
        self.admin = APIClient()
        self.admin.force_authenticate(make_admin())
        self.patient = make_patient('pat.chosen')

    def test_admin_checks_for_a_chosen_patient(self):
        r = self.admin.post(URL, {'text': REFLUX, 'patient_id': self.patient.id}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['patient'], {'id': self.patient.id, 'patient_id': self.patient.patient_id,
                                             'name': 'Hari Tamang'})
        self.assertEqual(RecommendationHistory.objects.get(id=r.data['history_id']).patient, self.patient)
        from apps.audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(description__contains=f'for patient {self.patient.patient_id}').exists())

    def test_admin_without_a_patient_is_a_guest_check(self):
        r = self.admin.post(URL, {'text': REFLUX}, format='json')
        self.assertIsNone(r.data['patient'])
        self.assertIsNone(RecommendationHistory.objects.get(id=r.data['history_id']).patient)

    def test_unknown_patient_rejected(self):
        for bad in (999999, 'abc'):
            r = self.admin.post(URL, {'text': REFLUX, 'patient_id': bad}, format='json')
            self.assertEqual((r.status_code, r.data['detail']), (400, 'Patient not found.'))
        self.assertEqual(RecommendationHistory.objects.count(), 0)

    def test_patient_cannot_check_for_someone_else(self):
        other = make_patient('pat.other', phone='9800000031', emergency='9800000032')
        client = APIClient()
        client.force_authenticate(self.patient.user)
        r = client.post(URL, {'text': REFLUX, 'patient_id': other.id}, format='json')
        self.assertEqual(RecommendationHistory.objects.get(id=r.data['history_id']).patient, self.patient)


def prioritise(**priorities):
    """Save a perfectly consistent AHP matrix from relative priorities (unnamed criteria count 1)."""
    p = [priorities.get(c, 1) for c in CRITERIA]
    RankingSettings.objects.update_or_create(pk=1, defaults={'ahp_pairwise': [[a / b for b in p] for a in p]})


class ExperienceRankingTests(TestCase):
    """TOPSIS uses the five criteria, weighted by the administrator's AHP comparisons."""

    def test_experience_breaks_a_tie(self):
        junior = doctor('dr.junior', 'Dermatology', first='Junior', experience_years=2)
        senior = doctor('dr.senior', 'Dermatology', first='Senior', experience_years=15)
        ranked = rank_doctors([junior, senior], today=date(2026, 9, 28))
        self.assertEqual([r['id'] for r in ranked], [senior.id, junior.id])
        self.assertEqual(ranked[0]['experience_years'], 15)
        self.assertIn('most experience', ranked[0]['reason'])

    def test_weights_come_from_ahp_settings(self):
        prioritise(experience=9)
        busy_senior = doctor('dr.busy', 'Dermatology', first='Busy', experience_years=20)
        assign(busy_senior, 3)
        free_junior = doctor('dr.free', 'Dermatology', first='Free', experience_years=1)
        ranked = rank_doctors([free_junior, busy_senior], today=date(2026, 9, 28))
        self.assertEqual(ranked[0]['id'], busy_senior.id)          # experience outweighs caseload here

    def test_free_hours_first(self):
        prioritise(free_hours=9)
        busy_senior = doctor('dr.busy', 'Dermatology', first='Busy', schedule={'Monday': '09:00-10:00'},
                             experience_years=20)
        free_junior = doctor('dr.free', 'Dermatology', first='Free', experience_years=1)
        ranked = rank_doctors([busy_senior, free_junior], today=date(2026, 9, 28))
        self.assertEqual(ranked[0]['id'], free_junior.id)

    def test_all_doctors_equal_still_ranked(self):
        a = doctor('dr.a', 'Dermatology', first='Anil', experience_years=5)
        b = doctor('dr.b', 'Dermatology', first='Bina', experience_years=5)
        ranked = rank_doctors([a, b], today=date(2026, 9, 28))
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]['score'], ranked[1]['score'])


_MODEL_STATE = ('_model', '_columns', '_implied', '_rates', '_rate_columns', '_vocabulary', '_loaded',
                '_load_error', '_retry_at', '_retry_delay')


class ModelUnavailableTests(TestCase):
    """The model file missing or unreadable: the cause is logged, loading is retried with
    backoff, and the endpoint answers 503 instead of an empty "no symptoms" result."""

    def setUp(self):
        saved = {name: getattr(symptom_model, name) for name in _MODEL_STATE}
        self.addCleanup(lambda: [setattr(symptom_model, k, v) for k, v in saved.items()])
        symptom_model._loaded, symptom_model._retry_at = False, None   # as at startup
        symptom_model._model = None

    def test_missing_file_is_logged_with_its_cause(self):
        missing = Path(__file__).parent / 'no-such-model.joblib'
        with self.assertLogs('ml.symptom_model', 'ERROR') as logs:
            self.assertFalse(symptom_model.load(missing))
        self.assertIn('does not exist', logs.output[0])
        self.assertIn('python -m ml.train_model', symptom_model.unavailable_reason())

    def test_blocked_library_is_logged_with_its_cause(self):
        blocked = ImportError('DLL load failed: An Application Control policy has blocked this file.')
        with mock.patch('joblib.load', side_effect=blocked), self.assertLogs('ml.symptom_model', 'ERROR') as logs:
            self.assertFalse(symptom_model.load())
        self.assertIn('Application Control policy', logs.output[0])
        self.assertIn('scikit-learn or joblib could not be imported', symptom_model.unavailable_reason())

    @override_settings(SMART_CHECK_MODEL_RETRY_SECONDS=30, SMART_CHECK_MODEL_RETRY_MAX_SECONDS=100)
    def test_failed_load_is_retried_with_exponential_backoff(self):
        now = [1000.0]
        with mock.patch('ml.symptom_model.time.monotonic', side_effect=lambda: now[0]), \
                mock.patch('joblib.load', side_effect=OSError('disk')) as joblib_load, \
                self.assertLogs('ml.symptom_model', 'ERROR'):
            for advance, delay in ((0, 30), (30, 60), (60, 100), (100, 100)):   # doubles, capped at 100
                now[0] += advance
                self.assertFalse(symptom_model.load())
                self.assertEqual(symptom_model._retry_delay, delay)
            calls = joblib_load.call_count
            now[0] += 50                        # before the next retry: the file is not read again
            self.assertFalse(symptom_model.load())
            self.assertEqual(joblib_load.call_count, calls)

    def test_endpoint_returns_503_not_an_empty_result(self):
        with mock.patch('joblib.load', side_effect=FileNotFoundError('symptom_model.joblib')), \
                self.assertLogs('apps.recommendations.smart_views', 'WARNING') as logs, \
                self.assertLogs('ml.symptom_model', 'ERROR'):
            r = APIClient().post(URL, {'text': REFLUX}, format='json')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data['status'], 'model_unavailable')
        self.assertEqual(r.data['fallback'], 'keyword')
        self.assertIn('not available right now', r.data['detail'])
        self.assertEqual(r.data['disclaimer'], DISCLAIMER)
        for key in ('symptoms', 'matched', 'negated', 'unrecognized'):   # never shown as "nothing found"
            self.assertNotIn(key, r.data)
        self.assertIn('does not exist', logs.output[0])
        self.assertEqual(RecommendationHistory.objects.count(), 0)
