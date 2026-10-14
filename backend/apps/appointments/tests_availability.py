import datetime as dt
from unittest import mock
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.appointments.availability import get_available_dates, get_available_slots
from apps.appointments.models import Appointment
from apps.doctors.models import DoctorLeave, DoctorSchedule
from apps.users.factories import make_doctor, make_patient

KTM = ZoneInfo('Asia/Kathmandu')
# Monday 5 October 2026, 10:10 in Kathmandu.
NOW = dt.datetime(2026, 10, 5, 10, 10, tzinfo=KTM)
TODAY = NOW.date()
NEXT_MONDAY = TODAY + dt.timedelta(days=7)


def t(hhmm):
    return dt.datetime.strptime(hhmm, '%H:%M').time()


def times(*values):
    return [t(v) for v in values]


class AvailabilityTestCase(TestCase):
    def setUp(self):
        # Mondays 09:00-11:00 in 30-minute slots; every other day closed.
        self.doctor = make_doctor(availability_schedule={'Monday': '09:00-11:00'})
        self.patient = make_patient()

    def book(self, day, at, status='PENDING', patient=None):
        return Appointment.objects.create(
            patient=patient or self.patient, doctor=self.doctor,
            appointment_date=day, appointment_time=t(at), status=status,
        )


class SlotGenerationTests(AvailabilityTestCase):
    def test_slots_follow_the_weekly_schedule(self):
        self.assertEqual(get_available_slots(self.doctor, NEXT_MONDAY, now=NOW),
                         times('09:00', '09:30', '10:00', '10:30'))

    def test_slot_length_is_respected_and_partial_slots_dropped(self):
        DoctorSchedule.objects.filter(doctor=self.doctor).update(slot_minutes=45)
        self.assertEqual(get_available_slots(self.doctor, NEXT_MONDAY, now=NOW), times('09:00', '09:45'))

    def test_unscheduled_weekday_has_no_slots(self):
        self.assertEqual(get_available_slots(self.doctor, NEXT_MONDAY + dt.timedelta(days=1), now=NOW), [])

    def test_inactive_schedule_has_no_slots(self):
        DoctorSchedule.objects.filter(doctor=self.doctor).update(is_active=False)
        self.assertEqual(get_available_slots(self.doctor, NEXT_MONDAY, now=NOW), [])

    def test_inactive_doctor_has_no_slots(self):
        self.doctor.status = 'Inactive'
        self.doctor.save()
        self.assertEqual(get_available_slots(self.doctor, NEXT_MONDAY, now=NOW), [])

    def test_past_day_has_no_slots(self):
        self.assertEqual(get_available_slots(self.doctor, TODAY - dt.timedelta(days=7), now=NOW), [])

    def test_leave_day_has_no_slots(self):
        DoctorLeave.objects.create(doctor=self.doctor, date=NEXT_MONDAY, reason='Conference')
        self.assertEqual(get_available_slots(self.doctor, NEXT_MONDAY, now=NOW), [])

    def test_booked_slots_removed_but_cancelled_ones_freed(self):
        self.book(NEXT_MONDAY, '09:00', 'PENDING')
        self.book(NEXT_MONDAY, '09:30', 'ACCEPTED')
        self.book(NEXT_MONDAY, '10:00', 'CANCELLED')
        self.assertEqual(get_available_slots(self.doctor, NEXT_MONDAY, now=NOW), times('10:00', '10:30'))

    def test_off_grid_booking_blocks_the_slot_it_falls_in(self):
        self.book(NEXT_MONDAY, '09:40')
        self.assertEqual(get_available_slots(self.doctor, NEXT_MONDAY, now=NOW), times('09:00', '10:00', '10:30'))

    def test_past_times_today_removed(self):
        # 10:10 now: 09:00, 09:30 and the 10:00 slot already under way are gone.
        self.assertEqual(get_available_slots(self.doctor, TODAY, now=NOW), times('10:30'))

    def test_slot_starting_right_now_is_past(self):
        now = NOW.replace(minute=30)
        self.assertEqual(get_available_slots(self.doctor, TODAY, now=now), [])

    def test_now_is_read_in_kathmandu_time(self):
        # 04:25 UTC is 10:10 in Kathmandu.
        utc_now = dt.datetime(2026, 10, 5, 4, 25, tzinfo=dt.timezone.utc)
        self.assertEqual(get_available_slots(self.doctor, TODAY, now=utc_now), times('10:30'))


class AvailableDatesTests(AvailabilityTestCase):
    def test_next_30_days_only_scheduled_days(self):
        self.assertEqual(get_available_dates(self.doctor, now=NOW), [
            dt.date(2026, 10, 5), dt.date(2026, 10, 12), dt.date(2026, 10, 19),
            dt.date(2026, 10, 26), dt.date(2026, 11, 2),
        ])

    def test_leave_and_fully_booked_days_excluded(self):
        DoctorLeave.objects.create(doctor=self.doctor, date=dt.date(2026, 10, 19))
        other = make_patient('pat2', phone='9800000011', emergency='9800000012')
        for at in ('09:00', '09:30', '10:00', '10:30'):
            self.book(dt.date(2026, 10, 12), at, patient=other)
        dates = get_available_dates(self.doctor, now=NOW)
        self.assertNotIn(dt.date(2026, 10, 12), dates)
        self.assertNotIn(dt.date(2026, 10, 19), dates)
        self.assertIn(dt.date(2026, 10, 26), dates)

    def test_today_dropped_once_its_slots_have_passed(self):
        late = NOW.replace(hour=10, minute=45)
        self.assertNotIn(TODAY, get_available_dates(self.doctor, now=late))


@override_settings(SECURE_SSL_REDIRECT=False)
@mock.patch('django.utils.timezone.now', return_value=NOW)
class AvailabilityApiTests(AvailabilityTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.patient.user)

    def post(self, day, at):
        return self.client.post('/api/v1/appointments/', {
            'doctor': self.doctor.id, 'appointment_date': day.isoformat(), 'appointment_time': at,
        }, format='json')

    def test_available_dates_endpoint(self, _now):
        r = self.client.get(f'/api/v1/doctors/{self.doctor.id}/available-dates/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['today'], '2026-10-05')
        self.assertEqual(r.data['dates'][:2], ['2026-10-05', '2026-10-12'])

    def test_available_slots_endpoint(self, _now):
        self.book(NEXT_MONDAY, '09:30')
        r = self.client.get(f'/api/v1/doctors/{self.doctor.id}/available-slots/',
                            {'date': NEXT_MONDAY.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['slots'], ['09:00', '10:00', '10:30'])

    def test_available_slots_rejects_bad_date(self, _now):
        r = self.client.get(f'/api/v1/doctors/{self.doctor.id}/available-slots/', {'date': '12/10/2026'})
        self.assertEqual(r.status_code, 400)

    def test_booking_an_offered_slot_succeeds(self, _now):
        self.assertEqual(self.post(NEXT_MONDAY, '10:30').status_code, 201)

    def test_booking_outside_hours_rejected(self, _now):
        r = self.post(NEXT_MONDAY, '11:00')
        self.assertEqual(r.status_code, 400)
        self.assertIn('appointment_time', r.data)

    def test_booking_off_the_slot_grid_rejected(self, _now):
        r = self.post(NEXT_MONDAY, '09:15')
        self.assertEqual(r.status_code, 400)
        self.assertIn('appointment_time', r.data)

    def test_booking_unscheduled_day_rejected(self, _now):
        r = self.post(NEXT_MONDAY + dt.timedelta(days=1), '09:00')
        self.assertEqual(r.status_code, 400)
        self.assertIn('appointment_date', r.data)

    def test_booking_leave_day_rejected(self, _now):
        DoctorLeave.objects.create(doctor=self.doctor, date=NEXT_MONDAY)
        r = self.post(NEXT_MONDAY, '09:00')
        self.assertEqual(r.status_code, 400)
        self.assertIn('on leave', str(r.data['appointment_date']))

    def test_booking_past_time_today_rejected(self, _now):
        r = self.post(TODAY, '09:30')
        self.assertEqual(r.status_code, 400)
        self.assertIn('appointment_time', r.data)

    def test_double_booking_returns_conflict(self, _now):
        self.book(NEXT_MONDAY, '09:00')
        r = self.post(NEXT_MONDAY, '09:00')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['code'], 'slot_taken')
        self.assertEqual(Appointment.objects.filter(appointment_date=NEXT_MONDAY).count(), 1)

    def test_race_lost_at_the_database_returns_conflict(self, _now):
        # Both requests passed validation; the constraint rejects the second insert.
        self.book(NEXT_MONDAY, '09:00')
        with mock.patch('apps.appointments.serializers.get_available_slots', return_value=[t('09:00')]):
            r = self.post(NEXT_MONDAY, '09:00')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['code'], 'slot_taken')
        self.assertEqual(Appointment.objects.filter(appointment_date=NEXT_MONDAY).count(), 1)


class DoubleBookingConstraintTests(AvailabilityTestCase):
    def test_database_rejects_two_open_bookings_for_one_slot(self):
        self.book(NEXT_MONDAY, '09:00', 'ACCEPTED')
        other = make_patient('pat2', phone='9800000011', emergency='9800000012')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.book(NEXT_MONDAY, '09:00', 'PENDING', patient=other)

    def test_cancelled_booking_does_not_hold_the_slot(self):
        self.book(NEXT_MONDAY, '09:00', 'CANCELLED')
        self.book(NEXT_MONDAY, '09:00', 'PENDING')


class ScheduleSyncTests(TestCase):
    def test_json_schedule_creates_and_updates_rows(self):
        doctor = make_doctor(availability_schedule={'Monday': '09:00-11:00', 'Tuesday': 'closed'})
        self.assertEqual(list(doctor.schedules.values_list('weekday', 'start_time', 'is_active')),
                         [(0, t('09:00'), True)])
        doctor.schedules.update(slot_minutes=20)

        doctor.availability_schedule = {'Monday': '10:00-12:00', 'Wednesday': '08:00-09:00'}
        doctor.save()
        monday = doctor.schedules.get(weekday=0)
        self.assertEqual((monday.start_time, monday.end_time, monday.slot_minutes), (t('10:00'), t('12:00'), 20))
        self.assertTrue(doctor.schedules.filter(weekday=2, is_active=True).exists())

        doctor.availability_schedule = {'Monday': 'closed'}
        doctor.save()
        self.assertFalse(doctor.schedules.filter(is_active=True).exists())

    def test_rows_rewrite_json(self):
        doctor = make_doctor(availability_schedule={'Monday': '09:00-11:00'})
        doctor.schedules.update(end_time=t('12:00'))
        DoctorSchedule.objects.create(doctor=doctor, weekday=4, start_time=t('14:00'),
                                      end_time=t('16:00'), is_active=False)
        doctor.sync_json_from_schedules()
        doctor.refresh_from_db()
        self.assertEqual(doctor.availability_schedule, {'Monday': '09:00-12:00', 'Friday': 'closed'})
