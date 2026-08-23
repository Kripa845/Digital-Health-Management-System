import re
import secrets
import string
import json
from datetime import date
from django.db import transaction
from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.doctors.models import Doctor, DoctorAssignment, Prescription, AccessRequest
from apps.users.username import doctor_username as _doctor_username
from apps.users.username import normalize_name as _normalize_name

User = get_user_model()


def _generate_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.isupper() for c in pwd)
            and any(c.islower() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd


class UserNestedCharField(serializers.CharField):
    def run_validation(self, data=serializers.empty):
        source = self.source or self.field_name
        if '.' in source and data is serializers.empty:
            leaf = source.split('.')[-1]
            dotted_key = source.replace('.', '_')
            data = self.parent.initial_data.get(leaf) or self.parent.initial_data.get(dotted_key) or serializers.empty
        return super().run_validation(data)


class DoctorSerializer(serializers.ModelSerializer):
    first_name = UserNestedCharField(source='user.first_name', required=True)
    last_name  = UserNestedCharField(source='user.last_name',  required=True)
    username   = serializers.CharField(write_only=True, required=False)
    password   = serializers.CharField(write_only=True, required=False)
    age        = serializers.IntegerField(read_only=True)
    user_id    = serializers.IntegerField(source='user.id', read_only=True)

    login_username = serializers.CharField(source='user.username', read_only=True)
    account_active = serializers.BooleanField(source='user.is_active', read_only=True)

    generated_username = serializers.SerializerMethodField()
    generated_password = serializers.SerializerMethodField()

    class Meta:
        model = Doctor
        fields = (
            'id', 'doctor_id', 'uuid_token', 'user', 'first_name', 'last_name',
            'license_number',
            'department', 'specialization', 'dob', 'age', 'gender',
            'phone', 'email', 'photo', 'status',
            'availability_schedule', 'registration_date',
            'username', 'password',
            'login_username', 'account_active',
            'generated_username', 'generated_password',
            'user_id',
        )
        read_only_fields = (
            'id', 'doctor_id', 'uuid_token', 'registration_date', 'user',
            'login_username', 'account_active', 'user_id',
        )

    def get_generated_username(self, obj):
        return getattr(obj, '_generated_username', None)

    def get_generated_password(self, obj):
        return getattr(obj, '_generated_password', None)

    def _validate_name(self, value, label):
        value = (value or '').strip()
        if len(value) < 2:
            raise serializers.ValidationError(f"{label} must be at least 2 characters long.")
        if len(value) > 50:
            raise serializers.ValidationError(f"{label} cannot exceed 50 characters.")
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError(f"{label} can contain letters only.")
        return _normalize_name(value)

    def validate_first_name(self, value):
        return self._validate_name(value, "First name")

    def validate_last_name(self, value):
        return self._validate_name(value, "Last name")

    def validate_email(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("Email is required.")
        value = str(value).strip()
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', value):
            raise serializers.ValidationError("Please enter a valid email address.")
        if any(c.isupper() for c in value):
            raise serializers.ValidationError("Email must contain only lowercase letters.")
        return value

    def validate_dob(self, value):
        if value > date.today():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        return value

    def validate_phone(self, value):
        pattern = r'^(98|97)\d{8}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError(
                "Phone number must be a valid Nepal mobile number "
                "(starting with 98 or 97 and exactly 10 digits)."
            )
        return value

    def validate_license_number(self, value):
       
        raw = (value or '').strip().upper()
        m = re.match(r'^(?:NMC[-\s]?(?:NO\.?\s*)?)?(\d{1,6})$', raw)
        if not m:
            raise serializers.ValidationError(
                "Enter a valid NMC number — the Nepal Medical Council registration "
                "number, e.g. NMC-12345 (up to 6 digits)."
            )
        normalized = f"NMC-{m.group(1)}"
        qs = Doctor.objects.filter(license_number=normalized)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This NMC number is already registered to another doctor.")
        return normalized

    def validate_availability_schedule(self, value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                raise serializers.ValidationError("Invalid JSON for availability schedule.")
        return value

    def create(self, validated_data):
        user_data = validated_data.pop('user', {})
        first_name = user_data.get('first_name', validated_data.pop('first_name', ''))
        last_name  = user_data.get('last_name',  validated_data.pop('last_name',  ''))
        username   = validated_data.pop('username', None)
        password   = validated_data.pop('password', None)

        final_password = password if password else _generate_password(10)

        with transaction.atomic():
            from apps.doctors.models import Doctor as DoctorModel
            doctor_id = DoctorModel.generate_doctor_id()

            if username:
                final_username = username
                counter = 2
                while User.objects.filter(username=final_username).exists():
                    final_username = f"{username}{counter}"
                    counter += 1
            else:
                final_username = _doctor_username(first_name, last_name, doctor_id)

            user = User.objects.create_user(
                username=final_username,
                password=final_password,
                first_name=first_name,
                last_name=last_name,
                email=validated_data.get('email', ''),
                role=User.Role.DOCTOR,
                must_change_password=True,
            )

            doctor = Doctor.objects.create(
                user=user,
                doctor_id=doctor_id,
                **validated_data,
            )

        doctor._generated_username = final_username
        doctor._generated_password = final_password if not password else '[PROVIDED]'
        return doctor

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        first_name = user_data.get('first_name', validated_data.pop('first_name', instance.user.first_name))
        last_name = user_data.get('last_name', validated_data.pop('last_name', instance.user.last_name))
        new_email = validated_data.get('email', instance.email)

        with transaction.atomic():
            user = instance.user
            user.first_name = first_name
            user.last_name = last_name
            user.email = new_email or ''
            user.save()
            return super().update(instance, validated_data)


class DoctorAssignmentSerializer(serializers.ModelSerializer):
    doctor_name = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    patient_custom_id = serializers.CharField(source='patient.patient_id', read_only=True)

    class Meta:
        model = DoctorAssignment
        fields = (
            'id', 'doctor', 'doctor_name',
            'patient', 'patient_name', 'patient_custom_id',
            'assigned_date', 'status',
        )
        read_only_fields = ('id', 'assigned_date', 'patient_custom_id', 'doctor_name', 'patient_name')

    def get_doctor_name(self, obj):
        return f"Dr. {obj.doctor.user.first_name} {obj.doctor.user.last_name}"

    def get_patient_name(self, obj):
        return f"{obj.patient.first_name} {obj.patient.last_name}"

    def validate(self, attrs):
        doctor  = attrs.get('doctor')
        patient = attrs.get('patient')
        if doctor and patient:
            if DoctorAssignment.objects.filter(doctor=doctor, patient=patient).exists():
                raise serializers.ValidationError(
                    "This patient is already assigned to this doctor."
                )
        return attrs


class PrescriptionSerializer(serializers.ModelSerializer):
    patient_name = serializers.SerializerMethodField(read_only=True)
    doctor_name = serializers.SerializerMethodField(read_only=True)
    patient_id_code = serializers.CharField(source='patient.patient_id', read_only=True)

    class Meta:
        model = Prescription
        fields = (
            'id', 'patient', 'patient_name', 'patient_id_code',
            'doctor', 'doctor_name',
            'diagnosis', 'medications', 'notes', 'prescription_date',
        )
        read_only_fields = ('id', 'doctor', 'prescription_date', 'patient_id_code', 'patient_name', 'doctor_name')

    def get_patient_name(self, obj):
        return f"{obj.patient.first_name} {obj.patient.last_name}"

    def get_doctor_name(self, obj):
        return f"Dr. {obj.doctor.get_full_name() or obj.doctor.username}"

    def validate_diagnosis(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Diagnosis is required.")
        return value

    def validate_medications(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Medications are required.")
        return value


class AccessRequestSerializer(serializers.ModelSerializer):
    doctor_name = serializers.SerializerMethodField(read_only=True)
    doctor_id_code = serializers.CharField(source='doctor.doctor_id', read_only=True)
    department = serializers.CharField(source='doctor.department', read_only=True)
    patient_name = serializers.SerializerMethodField(read_only=True)
    patient_id_code = serializers.CharField(source='patient.patient_id', read_only=True)

    class Meta:
        model = AccessRequest
        fields = (
            'id', 'doctor', 'doctor_name', 'doctor_id_code', 'department',
            'patient', 'patient_name', 'patient_id_code',
            'status', 'reason', 'created_at', 'resolved_at',
        )
        read_only_fields = (
            'id', 'doctor', 'status', 'created_at', 'resolved_at',
            'doctor_name', 'doctor_id_code', 'department',
            'patient_name', 'patient_id_code',
        )

    def get_doctor_name(self, obj):
        u = obj.doctor.user
        return f"Dr. {u.get_full_name() or u.username}"

    def get_patient_name(self, obj):
        return f"{obj.patient.first_name} {obj.patient.last_name}"
