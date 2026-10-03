from datetime import datetime as datetime_type

from django.utils import timezone
from rest_framework import serializers

from apps.appointments.models import Appointment
from apps.patients.serializers import PatientSummarySerializer
from apps.doctors.serializers import PublicDoctorSerializer


def _doctor_hours(doctor, day):
    """Return (start, end) times for the doctor on ``day``, 'closed', or None
    when the schedule does not say (in which case booking is allowed)."""
    schedule = doctor.availability_schedule or {}
    slot = str(schedule.get(day.strftime('%A'), '') or '').strip().lower()
    if not slot:
        return None
    if slot == 'closed':
        return 'closed'
    try:
        start, end = (datetime_type.strptime(part.strip(), '%H:%M').time() for part in slot.split('-', 1))
    except ValueError:
        return None
    return start, end


class AppointmentSerializer(serializers.ModelSerializer):
    # Identity only: an appointment does not grant access to the medical
    # record, which follows the doctor access rule in apps.doctors.access.
    patient_detail = PatientSummarySerializer(source='patient', read_only=True)
    doctor_detail = PublicDoctorSerializer(source='doctor', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)

    class Meta:
        model = Appointment
        fields = (
            'id', 'patient', 'patient_detail', 'doctor', 'doctor_detail',
            'appointment_date', 'appointment_time', 'status', 'reason', 'notes',
            'created_at', 'updated_at', 'approved_by', 'approved_by_name',
            'completed_at', 'cancelled_at'
        )
        read_only_fields = (
            'id', 'patient', 'status', 'created_at', 'updated_at', 'approved_by',
            'approved_by_name', 'completed_at', 'cancelled_at'
        )

    def create(self, validated_data):
        request = self.context.get('request')
        patient = getattr(getattr(request, 'user', None), 'patient_profile', None)
        if patient is None:
            raise serializers.ValidationError(
                {'patient': 'Only patients can book appointments.'}
            )
        validated_data['patient'] = patient
        validated_data['status'] = 'PENDING'
        return super().create(validated_data)

    def validate(self, attrs):
        appointment_date = attrs.get('appointment_date')
        appointment_time = attrs.get('appointment_time')
        doctor = attrs.get('doctor')

        # Compare in Kathmandu time, not the server's clock.
        now = timezone.localtime()
        today = now.date()

        if appointment_date and appointment_date < today:
            raise serializers.ValidationError({"appointment_date": "Appointment date cannot be in the past."})

        if appointment_date == today and appointment_time and appointment_time < now.time():
            raise serializers.ValidationError({"appointment_time": "Appointment time cannot be in the past."})

        if doctor is not None and (doctor.status != 'Active' or not doctor.user.is_active):
            raise serializers.ValidationError({"doctor": "This doctor is not currently taking appointments."})

        if doctor and appointment_date and appointment_time:
            hours = _doctor_hours(doctor, appointment_date)
            if hours == 'closed':
                raise serializers.ValidationError(
                    {"appointment_date": f"Dr. {doctor.user.last_name} does not see patients on {appointment_date.strftime('%A')}s."}
                )
            if hours and not (hours[0] <= appointment_time < hours[1]):
                raise serializers.ValidationError(
                    {"appointment_time": f"Dr. {doctor.user.last_name} sees patients between "
                                         f"{hours[0].strftime('%H:%M')} and {hours[1].strftime('%H:%M')} on that day."}
                )

            existing = Appointment.objects.filter(
                doctor=doctor,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                status__in=['PENDING', 'ACCEPTED']
            )
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({"non_field_errors": ["This time slot is already booked for the selected doctor."]})

        return attrs
