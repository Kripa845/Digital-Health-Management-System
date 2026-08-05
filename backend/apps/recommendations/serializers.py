from rest_framework import serializers
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.recommendations.models import RecommendationHistory
from apps.doctors.models import Doctor
from apps.doctors.serializers import DoctorSerializer

class RecommendationHistorySerializer(serializers.ModelSerializer):
    recommended_doctor_detail = DoctorSerializer(source='recommended_doctor', read_only=True)
    patient_name = serializers.SerializerMethodField(read_only=True)
    related_doctors = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = RecommendationHistory
        fields = (
            'id', 'patient', 'patient_name', 'symptoms', 'pain_level', 'age',
            'medical_history', 'recommended_doctor', 'recommended_doctor_detail',
            'related_doctors',
            'recommended_department', 'score', 'confidence', 'reason',
            'recommendation_date'
        )
        read_only_fields = (
            'id', 'recommended_doctor', 'recommended_doctor_detail',
            'related_doctors',
            'recommended_department', 'score', 'confidence', 'reason',
            'recommendation_date'
        )

    def get_patient_name(self, obj):
        if obj.patient:
            return f"{obj.patient.first_name} {obj.patient.last_name}"
        return "Guest"

    def get_related_doctors(self, obj):
        if not obj.recommended_doctor:
            return []
        dept = obj.recommended_department
        doctors = Doctor.objects.filter(department=dept, status='Active').exclude(id=obj.recommended_doctor.id)
        serializer = DoctorSerializer(doctors, many=True)
        return serializer.data

    def validate_age(self, value):
        if value is not None and not isinstance(value, int):
            raise serializers.ValidationError("Age must be a valid integer.")
        if value is not None and not (1 <= value <= 120):
            raise serializers.ValidationError("Age must be between 1 and 120 years.")
        return value
