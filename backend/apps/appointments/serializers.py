from rest_framework import serializers, status
from rest_framework.exceptions import APIException

from apps.appointments.availability import free_slots, local_now, doctor_is_bookable, get_available_slots
from apps.appointments.models import Appointment
from apps.doctors.models import DoctorLeave, DoctorSchedule
from apps.patients.serializers import PatientSummarySerializer
from apps.doctors.serializers import PublicDoctorSerializer

SLOT_TAKEN_MESSAGE = 'Sorry, that time was just booked by someone else. Please choose another time.'


class SlotTaken(APIException):
    """The slot is (or just became) held by another open appointment."""
    status_code = status.HTTP_409_CONFLICT
    default_code = 'slot_taken'

    def __init__(self):
        super().__init__({'detail': SLOT_TAKEN_MESSAGE, 'code': self.default_code})


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
        # The slot check in validate() reports a taken slot as a 409 the
        # booking form recognises; skip DRF's generic unique-together 400.
        validators = []

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
        now = local_now()
        today = now.date()

        if appointment_date and appointment_date < today:
            raise serializers.ValidationError({"appointment_date": "Appointment date cannot be in the past."})

        if doctor is not None and not doctor_is_bookable(doctor):
            raise serializers.ValidationError({"doctor": "This doctor is not currently taking appointments."})

        if doctor and appointment_date and appointment_time:
            self._validate_slot(doctor, appointment_date, appointment_time, now)

        return attrs

    def _validate_slot(self, doctor, day, at, now):
        """Re-check the requested slot against the doctor's schedule with the
        same rule the booking form used (get_available_slots)."""
        if at in get_available_slots(doctor, day, now=now):
            return
        name = f"Dr. {doctor.user.last_name}"
        if DoctorLeave.objects.filter(doctor=doctor, date=day).exists():
            raise serializers.ValidationError({"appointment_date": f"{name} is on leave on {day:%d %B %Y}."})
        schedule = DoctorSchedule.objects.filter(doctor=doctor, weekday=day.weekday(), is_active=True).first()
        if schedule is None:
            raise serializers.ValidationError(
                {"appointment_date": f"{name} does not see patients on {day:%A}s."}
            )
        if day == now.date() and at <= now.time():
            raise serializers.ValidationError({"appointment_time": "Appointment time cannot be in the past."})
        if at not in free_slots(day, [schedule], False, [], now):
            raise serializers.ValidationError({
                "appointment_time": f"{name} sees patients between {schedule.start_time:%H:%M} and "
                                    f"{schedule.end_time:%H:%M} on {day:%A}s, in {schedule.slot_minutes}-minute "
                                    f"slots. Please choose one of the offered times."
            })
        # In the schedule but no longer free: another open appointment holds it.
        raise SlotTaken()
