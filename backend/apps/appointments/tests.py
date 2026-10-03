import datetime as dt

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.users.factories import make_admin, make_doctor, make_patient


def _future_day(days=7):
    return timezone.localdate() + dt.timedelta(days=days)


@override_settings(SECURE_SSL_REDIRECT=False)
class AppointmentWorkflowTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.patient = make_patient()
        self.day = _future_day()
        self.doctor = make_doctor(availability_schedule={self.day.strftime('%A'): '09:00-17:00'})
        self.client = APIClient()

    def _book(self, **overrides):
        payload = {
            'doctor': self.doctor.id,
            'appointment_date': str(self.day),
            'appointment_time': '10:00',
            'reason': 'Check-up',
        }
        payload.update(overrides)
        self.client.force_authenticate(self.patient.user)
        return self.client.post('/api/v1/appointments/', payload, format='json')

    def _accepted(self):
        return Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, appointment_date=self.day,
            appointment_time=dt.time(10, 0), status='ACCEPTED',
        )

    def test_patient_can_book(self):
        r = self._book()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'PENDING')

    def test_patient_cannot_edit_or_delete_appointment(self):
        appt = self._accepted()
        self.client.force_authenticate(self.patient.user)
        r = self.client.patch(f'/api/v1/appointments/{appt.id}/', {'appointment_date': str(_future_day(9))}, format='json')
        self.assertEqual(r.status_code, 405)
        r = self.client.delete(f'/api/v1/appointments/{appt.id}/')
        self.assertEqual(r.status_code, 405)
        appt.refresh_from_db()
        self.assertEqual(appt.appointment_date, self.day)

    def test_patient_cannot_mark_completed(self):
        appt = self._accepted()
        self.client.force_authenticate(self.patient.user)
        r = self.client.post(f'/api/v1/appointments/{appt.id}/complete/')
        self.assertEqual(r.status_code, 403)
        appt.refresh_from_db()
        self.assertEqual(appt.status, 'ACCEPTED')

    def test_doctor_can_mark_completed(self):
        appt = self._accepted()
        self.client.force_authenticate(self.doctor.user)
        r = self.client.post(f'/api/v1/appointments/{appt.id}/complete/')
        self.assertEqual(r.status_code, 200)

    def test_double_booking_rejected(self):
        self.assertEqual(self._book().status_code, 201)
        other = make_patient('pat2', phone='9800000011', emergency='9800000012')
        self.client.force_authenticate(other.user)
        r = self.client.post('/api/v1/appointments/', {
            'doctor': self.doctor.id, 'appointment_date': str(self.day), 'appointment_time': '10:00',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_outside_doctor_hours_rejected(self):
        r = self._book(appointment_time='18:30')
        self.assertEqual(r.status_code, 400)
        self.assertIn('appointment_time', r.data)

    def test_closed_day_rejected(self):
        self.doctor.availability_schedule = {self.day.strftime('%A'): 'closed'}
        self.doctor.save()
        r = self._book()
        self.assertEqual(r.status_code, 400)
        self.assertIn('appointment_date', r.data)

    def test_inactive_doctor_rejected(self):
        self.doctor.status = 'Inactive'
        self.doctor.save()
        r = self._book()
        self.assertEqual(r.status_code, 400)
        self.assertIn('doctor', r.data)

    def test_appointment_hides_medical_record_and_doctor_contacts(self):
        self._book()
        self.client.force_authenticate(self.doctor.user)
        appt = self.client.get('/api/v1/appointments/').data[0]
        self.assertNotIn('allergies', appt['patient_detail'])
        self.assertNotIn('blood_pressure', appt['patient_detail'])
        self.assertNotIn('phone', appt['doctor_detail'])
        self.assertNotIn('license_number', appt['doctor_detail'])
