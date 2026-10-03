"""Tests for the smart symptom check endpoint (Naive Bayes + TOPSIS)."""
from datetime import date, time

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.doctors.models import DoctorAssignment
from apps.recommendations.models import RecommendationHistory
from apps.recommendations.smart_views import free_hours_this_week, rank_doctors
from apps.users.factories import make_doctor, make_patient
from ml import symptom_model

URL = '/api/v1/smart-symptom-check/'
SKIN = 'itching, skin rash and nodal skin eruptions'           # -> Dermatology
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
            raise AssertionError('Run "python -m ml.train_nb" first: ml/nb_model.joblib is missing.')

    def post(self, text, client=None):
        return (client or APIClient()).post(URL, {'text': text}, format='json')

    def test_ranks_department_doctors_with_topsis_and_saves_history(self):
        busy = doctor('dr.busy', 'Dermatology', first='Busy', last='Bista')
        free = doctor('dr.free', 'Dermatology', first='Free', last='Gurung')
        assign(busy, 3)
        r = self.post(SKIN)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['status'], r.data['department']), ('ok', 'Dermatology'))
        self.assertEqual(r.data['disclaimer'], DISCLAIMER)
        self.assertEqual(len(r.data['illnesses']), 3)
        names = [d['name'] for d in r.data['doctors']]
        self.assertEqual(names, ['Free Gurung', 'Busy Bista'])          # same hours, lighter caseload wins
        self.assertIn('lightest caseload', r.data['doctors'][0]['reason'])
        self.assertGreater(r.data['doctors'][0]['score'], r.data['doctors'][1]['score'])
        h = RecommendationHistory.objects.get(id=r.data['history_id'])
        self.assertEqual((h.recommended_department, h.recommended_doctor_id, h.symptoms),
                         ('Dermatology', free.id, SKIN))
        self.assertEqual(h.confidence, round(100 * r.data['dept_probability']))
        self.assertIn(DISCLAIMER, h.reason)
        self.assertIsNone(h.patient)                                    # guest

    def test_history_linked_to_logged_in_patient(self):
        doctor('dr.skin', 'Dermatology')
        patient = make_patient('pat.smart')
        client = APIClient()
        client.force_authenticate(patient.user)
        r = self.post(SKIN, client)
        self.assertEqual(RecommendationHistory.objects.get(id=r.data['history_id']).patient, patient)

    def test_exactly_one_doctor(self):
        only = doctor('dr.only', 'Dermatology')
        r = self.post(SKIN)
        self.assertEqual(len(r.data['doctors']), 1)
        self.assertEqual((r.data['doctors'][0]['id'], r.data['doctors'][0]['score']), (only.id, 1.0))
        self.assertEqual(r.data['doctors'][0]['reason'], 'only active doctor in this department')

    def test_no_doctor_in_department_falls_back_to_general_medicine(self):
        gp = doctor('dr.gp', 'General Medicine')
        r = self.post(SKIN)
        self.assertEqual(r.data['department'], 'Dermatology')           # the suggestion is unchanged
        self.assertEqual(r.data['doctors_department'], 'General Medicine')
        self.assertEqual([d['id'] for d in r.data['doctors']], [gp.id])
        self.assertIn('No Dermatology doctor', r.data['doctors_note'])

    def test_no_doctors_at_all(self):
        r = self.post(SKIN)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['doctors'], r.data['doctors_department']), ([], None))
        self.assertIn('Please contact the hospital', r.data['doctors_note'])
        self.assertIsNone(RecommendationHistory.objects.get(id=r.data['history_id']).recommended_doctor)

    def test_inactive_doctors_are_not_suggested(self):
        doctor('dr.off', 'Dermatology', status='Inactive')
        self.assertEqual(self.post(SKIN).data['doctors_department'], None)

    def test_top_three_only(self):
        for i in range(5):
            doctor(f'dr.d{i}', 'Dermatology', first=f'Doc{i}')
        self.assertEqual(len(self.post(SKIN).data['doctors']), 3)

    def test_not_ok_status_returned_as_is_and_not_saved(self):
        for text, expected in (('I only have itching', 'not_enough_info'),
                               ('no itching, no skin rash', 'not_enough_info'),
                               ('headache and cough', 'low_confidence')):
            r = self.post(text)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data['status'], expected, text)
            self.assertEqual(r.data['disclaimer'], DISCLAIMER)
            self.assertNotIn('doctors', r.data)
        self.assertEqual(RecommendationHistory.objects.count(), 0)

    def test_empty_and_very_long_text_rejected(self):
        for text in ('', '   '):
            self.assertEqual(self.post(text).status_code, 400)
        r = self.post('itching ' * 400)                                  # 3200 characters
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
        r = self.admin.post(URL, {'text': SKIN, 'patient_id': self.patient.id}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['patient'], {'id': self.patient.id, 'patient_id': self.patient.patient_id,
                                             'name': 'Hari Tamang'})
        self.assertEqual(RecommendationHistory.objects.get(id=r.data['history_id']).patient, self.patient)
        from apps.audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(description__contains=f'for patient {self.patient.patient_id}').exists())

    def test_admin_without_a_patient_is_a_guest_check(self):
        r = self.admin.post(URL, {'text': SKIN}, format='json')
        self.assertIsNone(r.data['patient'])
        self.assertIsNone(RecommendationHistory.objects.get(id=r.data['history_id']).patient)

    def test_unknown_patient_rejected(self):
        for bad in (999999, 'abc'):
            r = self.admin.post(URL, {'text': SKIN, 'patient_id': bad}, format='json')
            self.assertEqual((r.status_code, r.data['detail']), (400, 'Patient not found.'))
        self.assertEqual(RecommendationHistory.objects.count(), 0)

    def test_patient_cannot_check_for_someone_else(self):
        other = make_patient('pat.other', phone='9800000031', emergency='9800000032')
        client = APIClient()
        client.force_authenticate(self.patient.user)
        r = client.post(URL, {'text': SKIN, 'patient_id': other.id}, format='json')
        self.assertEqual(RecommendationHistory.objects.get(id=r.data['history_id']).patient, self.patient)
