from datetime import date as date_type, time as time_type, datetime as datetime_type
from rest_framework import serializers
from apps.appointments.models import Appointment
from apps.patients.serializers import PatientSerializer
from apps.doctors.serializers import DoctorSerializer

class AppointmentSerializer(serializers.ModelSerializer):
    patient_detail = PatientSerializer(source='patient', read_only=True)
    doctor_detail = DoctorSerializer(source='doctor', read_only=True)
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
        patient = attrs.get('patient')
        today = date_type.today()
        now = datetime_type.now().time()

        if appointment_date and appointment_date < today:
            raise serializers.ValidationError({"appointment_date": "Appointment date cannot be in the past."})

        if appointment_date == today and appointment_time and appointment_time < now:
            raise serializers.ValidationError({"appointment_time": "Appointment time cannot be in the past."})

        if doctor and appointment_date and appointment_time:
            existing = Appointment.objects.filter(
                doctor=doctor,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                status__in=['PENDING', 'ACCEPTED']
            ).exists()
            if existing:
                raise serializers.ValidationError({"non_field_errors": ["This time slot is already booked for the selected doctor."]})

        return attrs
