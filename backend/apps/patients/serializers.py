import re
import unicodedata
from datetime import date

from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.patients.models import Patient
from apps.users.credentials import generate_password
from apps.users.username import (
    is_valid_person_name,
    normalize_name as _normalize_name,
    patient_username as _patient_username,
    unique_username,
)

User = get_user_model()

# Every clinical value stored on the patient (kept in sync with the model).
CLINICAL_FIELDS = (
    'blood_pressure', 'blood_sugar_fasting', 'blood_sugar_random', 'hemoglobin',
    'cholesterol_total', 'cholesterol_hdl', 'cholesterol_ldl', 'triglycerides',
    'heart_rate', 'spo2', 'temperature', 'hba1c', 'serum_creatinine', 'blood_urea',
    'uric_acid', 'ssgpt_alt', 'ssgot_ast', 'bilirubin_total', 'tsh', 't3', 't4',
    'sodium', 'potassium', 'wbc_count', 'rbc_count', 'platelet_count', 'hematocrit', 'esr',
)


# Serializer

class PublicPatientSerializer(serializers.ModelSerializer):
    """What anyone holding the QR card may see: enough to identify the patient
    and help in an emergency, and nothing that enables identity theft
    (no date of birth, own phone number or internal database id)."""
    age = serializers.IntegerField(read_only=True)
    uuid = serializers.UUIDField(source='uuid_token', read_only=True)

    class Meta:
        model = Patient
        fields = (
            'uuid', 'patient_id',
            'first_name', 'middle_name', 'last_name',
            'photo', 'age', 'gender', 'blood_group',
            'emergency_contact',
            'status',
        )
        read_only_fields = fields


class PatientSummarySerializer(serializers.ModelSerializer):
    """Identity-only view of a patient, used where the viewer may not have
    access to the medical record (e.g. inside an appointment)."""
    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Patient
        fields = (
            'id', 'patient_id', 'first_name', 'middle_name', 'last_name',
            'age', 'gender', 'phone', 'photo',
        )
        read_only_fields = fields


class PatientSerializer(serializers.ModelSerializer):
    # Typed by the admin; "79028232" and "PAT-79028232" are both stored as PAT-79028232.
    patient_id = serializers.CharField(max_length=32)
    username = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    age = serializers.IntegerField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    login_username = serializers.CharField(source='user.username', read_only=True)
    account_active = serializers.BooleanField(source='user.is_active', read_only=True)

    class Meta:
        model = Patient
        fields = (
            'id', 'patient_id', 'uuid_token', 'user',
            'first_name', 'middle_name', 'last_name',
            'dob', 'age', 'gender', 'blood_group',
            'phone', 'emergency_contact', 'email', 'address',
            'height', 'weight',
            *CLINICAL_FIELDS,
            'allergies', 'current_medication',
            'prescription', 'pain_log',
            'status', 'photo',
            'registration_date', 'last_updated',
            'created_by', 'created_by_name',
            'username', 'password',
            'login_username', 'account_active',
        )
        read_only_fields = (
            'id', 'uuid_token', 'user',
            'age', 'registration_date', 'last_updated', 'created_by',
            'login_username', 'account_active',
        )

    def validate_patient_id(self, value):
        # The "PAT" prefix is optional when typing; only the code after it matters.
        code = re.sub(r'[\s\-]', '', value.upper())
        if code.startswith('PAT'):
            code = code[3:]
        digits = re.sub(r'\D', '', code)
        if not re.fullmatch(r'[A-Z0-9]{4,12}', code) or len(digits) < 4:
            raise serializers.ValidationError(
                "Enter the patient ID number: 4 to 12 letters or digits with at least 4 digits, e.g. 79028232."
            )
        value = f'PAT-{code}'
        others = Patient.objects.all()
        if self.instance is not None and isinstance(self.instance, Patient):
            others = others.exclude(pk=self.instance.pk)
        if others.filter(patient_id__iexact=value).exists():
            raise serializers.ValidationError(f"A patient with ID {value} already exists.")
        # Lab reports are matched on the ID's digits alone, so they must be unique too.
        for other_id in others.values_list('patient_id', flat=True):
            if re.sub(r'\D', '', other_id) == digits:
                raise serializers.ValidationError(
                    f"Patient {other_id} already uses the number {digits}. Lab reports are matched on the "
                    "number, so choose a different one."
                )
        return value

    def validate_first_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("First name must be at least 2 characters long.")
        if len(value) > 50:
            raise serializers.ValidationError("First name cannot exceed 50 characters.")
        if not is_valid_person_name(value):
            raise serializers.ValidationError("First name can contain letters, spaces, hyphens, apostrophes and dots only.")
        return _normalize_name(value)

    def validate_middle_name(self, value):
        if not value:
            return value
        value = value.strip()
        if len(value) > 50:
            raise serializers.ValidationError("Middle name cannot exceed 50 characters.")
        if not is_valid_person_name(value):
            raise serializers.ValidationError("Middle name can contain letters, spaces, hyphens, apostrophes and dots only.")
        return _normalize_name(value)

    def validate_last_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Last name must be at least 2 characters long.")
        if len(value) > 50:
            raise serializers.ValidationError("Last name cannot exceed 50 characters.")
        if not is_valid_person_name(value):
            raise serializers.ValidationError("Last name can contain letters, spaces, hyphens, apostrophes and dots only.")
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
        if not all(
            unicodedata.category(c)[0] in ('L', 'M', 'N') or c in " ,.-/#()'\n"
            for c in value
        ):
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
            raise serializers.ValidationError("Haemoglobin must be between 1 and 25 g/dL.")
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

        final_password = custom_password if custom_password else generate_password(10)

        patient_id = validated_data.pop('patient_id')

        try:
            with transaction.atomic():
                patient = self._create_account(validated_data, patient_id, custom_username, final_password, created_by)
        except IntegrityError:
            # Another admin saved the same ID between validation and save.
            if Patient.objects.filter(patient_id__iexact=patient_id).exists():
                raise serializers.ValidationError({'patient_id': [f"A patient with ID {patient_id} already exists."]})
            raise

        patient._generated_username = patient.user.username
        patient._generated_password = final_password if not custom_password else '[PROVIDED]'

        return patient

    def _create_account(self, validated_data, patient_id, custom_username, final_password, created_by):
        """Create the login and the patient record (runs inside a transaction)."""
        if custom_username:
            final_username = unique_username(custom_username)
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
        return patient

    # Update

    def update(self, instance, validated_data):
        validated_data.pop('username', None)
        validated_data.pop('password', None)

        first_name = validated_data.get('first_name', instance.first_name)
        last_name = validated_data.get('last_name', instance.last_name)
        email = validated_data.get('email', instance.email)

        try:
            with transaction.atomic():
                user = instance.user
                user.first_name = first_name
                user.last_name = last_name
                user.email = email or ''
                user.save(update_fields=['first_name', 'last_name', 'email'])
                return super().update(instance, validated_data)
        except IntegrityError:
            # Another admin took the same patient ID between validation and save.
            new_id = validated_data.get('patient_id')
            if new_id and Patient.objects.filter(patient_id__iexact=new_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError({'patient_id': [f"A patient with ID {new_id} already exists."]})
            raise


# Fields a patient may change on their own record. Date of birth, gender and
# blood group identify the patient (lab report identity check, QR card) and
# medical details are kept by the care team, so those stay admin-only. A name
# change is allowed but reported to the admins (see PatientViewSet.me).
PATIENT_NAME_FIELDS = ('first_name', 'middle_name', 'last_name')
PATIENT_SELF_EDITABLE_FIELDS = PATIENT_NAME_FIELDS + ('phone', 'emergency_contact', 'email', 'address', 'photo')

MAX_PHOTO_SIZE = 5 * 1024 * 1024


class PatientSelfUpdateSerializer(serializers.ModelSerializer):
    """A patient editing their own contact details and photo."""

    class Meta:
        model = Patient
        fields = PATIENT_SELF_EDITABLE_FIELDS

    # Same rules as when an admin edits these fields.
    validate_first_name = PatientSerializer.validate_first_name
    validate_middle_name = PatientSerializer.validate_middle_name
    validate_last_name = PatientSerializer.validate_last_name
    validate_phone = PatientSerializer.validate_phone
    validate_emergency_contact = PatientSerializer.validate_emergency_contact
    validate_email = PatientSerializer.validate_email
    validate_address = PatientSerializer.validate_address

    def validate_photo(self, value):
        if value and value.size > MAX_PHOTO_SIZE:
            raise serializers.ValidationError("Photo must be 5 MB or smaller.")
        return value

    def validate(self, attrs):
        # Compare with the saved number when only one of the two is being changed.
        phone = attrs.get('phone', self.instance.phone if self.instance else None)
        emergency = attrs.get('emergency_contact', self.instance.emergency_contact if self.instance else None)
        if phone and emergency and phone == emergency:
            raise serializers.ValidationError({
                'emergency_contact': (
                    "Emergency contact number should be different from your own number."
                )
            })
        return attrs

    def update(self, instance, validated_data):
        with transaction.atomic():
            # The login account keeps the same name and email as the patient record.
            # (The username stays the same, so the patient signs in as before.)
            user, user_fields = instance.user, []
            for field in ('first_name', 'last_name', 'email'):
                if field in validated_data:
                    setattr(user, field, validated_data[field] or '')
                    user_fields.append(field)
            if user_fields:
                user.save(update_fields=user_fields)
            return super().update(instance, validated_data)
