import re
import secrets
import string
from datetime import date

from django.db import transaction
from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.patients.models import Patient

User = get_user_model()


# Helpers

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


def _unique_username(base: str) -> str:
    candidate = base
    counter = 2
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


from apps.users.username import patient_username as _patient_username
from apps.users.username import normalize_name as _normalize_name


# Serializer

class PatientSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    age = serializers.IntegerField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    login_username = serializers.CharField(source='user.username', read_only=True)
    account_active = serializers.BooleanField(source='user.is_active', read_only=True)

    generated_username = serializers.SerializerMethodField()
    generated_password = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = (
            'id', 'patient_id', 'uuid_token', 'user',
            'first_name', 'middle_name', 'last_name',
            'dob', 'age', 'gender', 'blood_group',
            'phone', 'emergency_contact', 'email', 'address',
            'height', 'weight',
            # ── Clinical vitals (auto-updated by lab report OCR / CDSA) ──
            'blood_pressure',
            'blood_sugar_fasting',
            'blood_sugar_random',
            'hemoglobin',
            'cholesterol_total',
            'cholesterol_hdl',
            'cholesterol_ldl',
            'triglycerides',
            # ─────────────────────────────────────────────────────────────
            'allergies', 'current_medication',
            'prescription', 'pain_log',
            'status', 'photo',
            'registration_date', 'last_updated',
            'created_by', 'created_by_name',
            'username', 'password',
            'login_username', 'account_active',
            'generated_username', 'generated_password',
        )
        read_only_fields = (
            'id', 'patient_id', 'uuid_token', 'user',
            'age', 'registration_date', 'last_updated', 'created_by',
        )
        read_only_fields = (
            'id', 'patient_id', 'uuid_token', 'user',
            'age', 'registration_date', 'last_updated', 'created_by',
            'login_username', 'account_active',
        )

    def get_generated_username(self, obj):
        return getattr(obj, '_generated_username', None)

    def get_generated_password(self, obj):
        return getattr(obj, '_generated_password', None)

    def validate_first_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("First name must be at least 2 characters long.")
        if len(value) > 50:
            raise serializers.ValidationError("First name cannot exceed 50 characters.")
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError("First name can contain letters only.")
        return _normalize_name(value)

    def validate_middle_name(self, value):
        if not value:
            return value
        value = value.strip()
        if len(value) > 50:
            raise serializers.ValidationError("Middle name cannot exceed 50 characters.")
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError("Middle name can contain letters only.")
        return _normalize_name(value)

    def validate_last_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Last name must be at least 2 characters long.")
        if len(value) > 50:
            raise serializers.ValidationError("Last name cannot exceed 50 characters.")
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError("Last name can contain letters only.")
        return _normalize_name(value)

    def validate_dob(self, value):
        if value > date.today():
            raise serializers.ValidationError("Date of birth cannot be a future date.")
        age = (
            date.today().year - value.year
            - ((date.today().month, date.today().day) < (value.month, value.day))
        )
        if age > 120:
            raise serializers.ValidationError("Age must be between 0 and 120 years.")
        return value

    def validate_phone(self, value):
        if not re.match(r'^(98|97)\d{8}$', value):
            raise serializers.ValidationError(
                "Please enter a valid Nepal mobile number (starting with 98 or 97, exactly 10 digits)."
            )
        return value

    def validate_emergency_contact(self, value):
        if not re.match(r'^(98|97)\d{8}$', value):
            raise serializers.ValidationError(
                "Please enter a valid emergency contact number (starting with 98 or 97, exactly 10 digits)."
            )
        return value

    def validate_address(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError("Address must be at least 5 characters long.")
        if len(value) > 255:
            raise serializers.ValidationError("Address cannot exceed 255 characters.")
        if not re.match(r'^[A-Za-z0-9 ,\-\/]+$', value):
            raise serializers.ValidationError("Please enter a valid address.")
        return value

    def validate_email(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("Email is required.")
        value = str(value).strip()
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', value):
            raise serializers.ValidationError("Please enter a valid email address.")
        if any(c.isupper() for c in value):
            raise serializers.ValidationError("Email must contain only lowercase letters.")
        return value

    def validate_height(self, value):
        if value is not None and not (30 <= float(value) <= 250):
            raise serializers.ValidationError("Height must be between 30 cm and 250 cm.")
        return value

    def validate_weight(self, value):
        if value is not None and not (1 <= float(value) <= 300):
            raise serializers.ValidationError("Weight must be between 1 kg and 300 kg.")
        return value

    def validate_hemoglobin(self, value):
        if value is not None and not (1 <= float(value) <= 25):
            raise serializers.ValidationError("Hemoglobin must be between 1 and 25 g/dL.")
        return value

    def validate_blood_sugar_fasting(self, value):
        if value is not None and not (20 <= float(value) <= 600):
            raise serializers.ValidationError("Fasting blood sugar must be between 20 and 600 mg/dL.")
        return value

    def validate_blood_sugar_random(self, value):
        if value is not None and not (20 <= float(value) <= 600):
            raise serializers.ValidationError("Random blood sugar must be between 20 and 600 mg/dL.")
        return value

    def validate_cholesterol_total(self, value):
        if value is not None and not (50 <= float(value) <= 700):
            raise serializers.ValidationError("Total cholesterol must be between 50 and 700 mg/dL.")
        return value

    def validate_cholesterol_hdl(self, value):
        if value is not None and not (5 <= float(value) <= 200):
            raise serializers.ValidationError("HDL cholesterol must be between 5 and 200 mg/dL.")
        return value

    def validate_cholesterol_ldl(self, value):
        if value is not None and not (10 <= float(value) <= 500):
            raise serializers.ValidationError("LDL cholesterol must be between 10 and 500 mg/dL.")
        return value

    def validate_triglycerides(self, value):
        if value is not None and not (20 <= float(value) <= 2000):
            raise serializers.ValidationError("Triglycerides must be between 20 and 2000 mg/dL.")
        return value

    def validate_blood_pressure(self, value):
        import re
        if value and not re.match(r'^\d{2,3}/\d{2,3}$', value.strip()):
            raise serializers.ValidationError(
                "Blood pressure must be in the format SYS/DIA, e.g. 120/80."
            )
        return value.strip() if value else value

    def validate_allergies(self, value):
        if value and len(value) > 500:
            raise serializers.ValidationError("Allergy information cannot exceed 500 characters.")
        return value

    def validate_current_medication(self, value):
        if value and len(value) > 1000:
            raise serializers.ValidationError("Medication details cannot exceed 1000 characters.")
        return value

    def validate_prescription(self, value):
        if value and len(value) > 2000:
            raise serializers.ValidationError("Prescription details cannot exceed 2000 characters.")
        return value

    def validate(self, attrs):
        phone = attrs.get('phone')
        emergency = attrs.get('emergency_contact')
        if phone and emergency and phone == emergency:
            raise serializers.ValidationError({
                'emergency_contact': (
                    "Emergency contact number should be different from the patient's contact number."
                )
            })
        return attrs

    # Create

    def create(self, validated_data):
        custom_username = validated_data.pop('username', None) or None
        custom_password = validated_data.pop('password', None) or None

        request = self.context.get('request')
        created_by = request.user if (request and request.user.is_authenticated) else None

        final_password = custom_password if custom_password else _generate_password(10)

        with transaction.atomic():
            patient_id = Patient.generate_patient_id()

            if custom_username:
                final_username = _unique_username(custom_username)
            else:
                final_username = _patient_username(
                    validated_data.get('first_name', ''),
                    validated_data.get('last_name', ''),
                    patient_id,
                )

            user = User.objects.create_user(
                username=final_username,
                password=final_password,
                first_name=validated_data.get('first_name', ''),
                last_name=validated_data.get('last_name', ''),
                email=validated_data.get('email', '') or '',
                role=User.Role.PATIENT,
                is_active=True,
                must_change_password=True,
            )

            patient = Patient(
                user=user,
                patient_id=patient_id,
                created_by=created_by,
                **validated_data,
            )
            patient.save()

        patient._generated_username = final_username
        patient._generated_password = final_password if not custom_password else '[PROVIDED]'

        return patient

    # Update

    def update(self, instance, validated_data):
        validated_data.pop('username', None)
        validated_data.pop('password', None)

        first_name = validated_data.get('first_name', instance.first_name)
        last_name = validated_data.get('last_name', instance.last_name)
        email = validated_data.get('email', instance.email)

        with transaction.atomic():
            user = instance.user
            user.first_name = first_name
            user.last_name = last_name
            user.email = email or ''
            user.save(update_fields=['first_name', 'last_name', 'email'])
            return super().update(instance, validated_data)
