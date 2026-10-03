import uuid
from django.core.validators import RegexValidator
from django.db import models
from django.conf import settings

# Typed by the admin when the patient is registered, e.g. PAT-9C0E059C.
PATIENT_ID_PATTERN = r'^PAT-[A-Z0-9]{4,12}$'
validate_patient_id_format = RegexValidator(
    PATIENT_ID_PATTERN,
    "Patient ID must be PAT- followed by 4 to 12 capital letters or digits, e.g. PAT-9C0E059C.",
)


class Patient(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='patient_profile'
    )
    patient_id = models.CharField(
        max_length=16, unique=True, db_index=True, validators=[validate_patient_id_format],
    )
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
    heart_rate         = models.PositiveSmallIntegerField(blank=True, null=True, help_text='Heart rate in bpm')
    spo2               = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='SpO2 percentage')
    temperature        = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True, help_text='Body temperature')
    hba1c              = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True, help_text='HbA1c %')
    serum_creatinine   = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='Serum creatinine mg/dL')
    blood_urea         = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='Blood urea mg/dL')
    uric_acid          = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True, help_text='Uric acid mg/dL')
    ssgpt_alt          = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='SGPT/ALT U/L')
    ssgot_ast          = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='SGOT/AST U/L')
    bilirubin_total    = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True, help_text='Total bilirubin mg/dL')
    tsh                = models.DecimalField(max_digits=6, decimal_places=3, blank=True, null=True, help_text='TSH mIU/L')
    t3                 = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='T3 ng/dL')
    t4                 = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='T4 μg/dL')
    sodium             = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='Sodium mEq/L')
    potassium          = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True, help_text='Potassium mEq/L')
    wbc_count          = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text='WBC count')
    rbc_count          = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='RBC count')
    platelet_count     = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text='Platelet count')
    hematocrit         = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True, help_text='Hematocrit %')
    esr                = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, help_text='ESR mm/hr')

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

    def save(self, *args, **kwargs):
        if not self.patient_id:
            raise ValueError("patient_id is required; the admin types it when registering the patient.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient_id} - {self.first_name} {self.last_name}"
