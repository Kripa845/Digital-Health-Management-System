import uuid
from django.db import models
from django.conf import settings


def _generate_patient_id() -> str:
    return f"PAT-{uuid.uuid4().hex[:8].upper()}"


class Patient(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='patient_profile'
    )
    patient_id = models.CharField(max_length=15, unique=True, editable=False, db_index=True)
    uuid_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    first_name = models.CharField(max_length=50)
    middle_name = models.CharField(max_length=50, blank=True, null=True)
    last_name = models.CharField(max_length=50)
    dob = models.DateField()
    gender = models.CharField(
        max_length=10,
        choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
    )
    blood_group = models.CharField(
        max_length=5,
        choices=[
            ('A+', 'A+'), ('A-', 'A-'),
            ('B+', 'B+'), ('B-', 'B-'),
            ('AB+', 'AB+'), ('AB-', 'AB-'),
            ('O+', 'O+'), ('O-', 'O-'),
        ],
    )
    phone = models.CharField(max_length=15)
    emergency_contact = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField()
    height = models.DecimalField(max_digits=5, decimal_places=2, help_text='Height in cm')
    weight = models.DecimalField(max_digits=5, decimal_places=2, help_text='Weight in kg')

    # ── Clinical vitals (auto-updated by lab report OCR / CDSA) ──────────────
    blood_pressure     = models.CharField(max_length=20,  blank=True, null=True, help_text='e.g. 120/80 mmHg')
    blood_sugar_fasting= models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text='Fasting blood sugar mg/dL')
    blood_sugar_random = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text='Random blood sugar mg/dL')
    hemoglobin         = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='Hemoglobin g/dL')
    cholesterol_total  = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text='Total cholesterol mg/dL')
    cholesterol_hdl    = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text='HDL cholesterol mg/dL')
    cholesterol_ldl    = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text='LDL cholesterol mg/dL')
    triglycerides      = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text='Triglycerides mg/dL')

    allergies = models.TextField(blank=True, null=True)
    current_medication = models.TextField(blank=True, null=True)
    prescription = models.TextField(blank=True, null=True)
    pain_log = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
        default='Active',
    )
    photo = models.ImageField(upload_to='patient_photos/', blank=True, null=True)

    registration_date = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_patients',
    )
    last_updated = models.DateTimeField(auto_now=True)

    @property
    def age(self):
        from datetime import date
        today = date.today()
        return (
            today.year - self.dob.year
            - ((today.month, today.day) < (self.dob.month, self.dob.day))
        )

    @classmethod
    def generate_patient_id(cls) -> str:
        for _ in range(10):
            candidate = _generate_patient_id()
            if not cls.objects.filter(patient_id=candidate).exists():
                return candidate
        # Fallback
        return f"PAT-{uuid.uuid4().hex[:8].upper()}"

    def save(self, *args, **kwargs):
        if not self.patient_id:
            self.patient_id = self.__class__.generate_patient_id()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient_id} - {self.first_name} {self.last_name}"
