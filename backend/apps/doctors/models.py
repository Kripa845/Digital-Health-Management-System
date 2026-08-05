import uuid
from django.db import models, transaction
from django.conf import settings


def _generate_doctor_id() -> str:
    return f"DOC-{uuid.uuid4().hex[:8].upper()}"


class Doctor(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='doctor_profile'
    )
    doctor_id   = models.CharField(max_length=15, unique=True, editable=False, db_index=True)
    uuid_token  = models.UUIDField(unique=True, editable=False, db_index=True)

    license_number = models.CharField(max_length=50, unique=True)
    department = models.CharField(
        max_length=50,
        choices=[
            ('General Medicine', 'General Medicine'),
            ('Cardiology', 'Cardiology'),
            ('Neurology', 'Neurology'),
            ('Dermatology', 'Dermatology'),
            ('Pediatrics', 'Pediatrics'),
            ('Gynecology', 'Gynecology'),
            ('Orthopedics', 'Orthopedics'),
            ('ENT', 'ENT'),
            ('Ophthalmology', 'Ophthalmology'),
            ('Psychiatry', 'Psychiatry'),
            ('Oncology', 'Oncology'),
            ('Urology', 'Urology'),
            ('Gastroenterology', 'Gastroenterology'),
            ('Nephrology', 'Nephrology'),
            ('Endocrinology', 'Endocrinology'),
            ('Pulmonology', 'Pulmonology'),
            ('Emergency Medicine', 'Emergency Medicine'),
            ('Family Medicine', 'Family Medicine'),
            ('Dentistry', 'Dentistry'),
            ('Radiology', 'Radiology'),
            ('Pathology', 'Pathology'),
        ],
    )
    specialization = models.CharField(max_length=100)
    dob    = models.DateField()
    gender = models.CharField(
        max_length=10,
        choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
    )
    phone  = models.CharField(max_length=15)
    email  = models.EmailField()
    photo  = models.ImageField(upload_to='doctor_photos/', blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
        default='Active',
    )
    availability_schedule = models.JSONField(
        default=dict,
        help_text="e.g. {'Monday': '09:00-17:00', 'Tuesday': '09:00-17:00'}",
    )
    registration_date = models.DateTimeField(auto_now_add=True)

    @property
    def age(self):
        from datetime import date
        today = date.today()
        return (
            today.year - self.dob.year
            - ((today.month, today.day) < (self.dob.month, self.dob.day))
        )

    @classmethod
    def generate_doctor_id(cls) -> str:
        for _ in range(10):
            candidate = _generate_doctor_id()
            if not cls.objects.filter(doctor_id=candidate).exists():
                return candidate
        return _generate_doctor_id()

    def save(self, *args, **kwargs):
        if not self.doctor_id:
            self.doctor_id = self.__class__.generate_doctor_id()
        if not self.uuid_token:
            self.uuid_token = uuid.uuid4()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.doctor_id} - Dr. {self.user.first_name} {self.user.last_name}"
            f" ({self.department})"
        )


class DoctorAssignment(models.Model):
    doctor  = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='assignments')
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.CASCADE, related_name='assignments'
    )
    assigned_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=15,
        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
        default='Active',
    )

    class Meta:
        pass

    def __str__(self):
        return f"Dr. {self.doctor.user.last_name} -> {self.patient.patient_id}"


class AccessRequest(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('DECLINED', 'Declined'),
    ]
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='access_requests')
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.CASCADE, related_name='access_requests'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resolved_access_requests',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f"AccessRequest: Dr. {self.doctor.user.last_name} -> {self.patient.patient_id} ({self.status})"


class Prescription(models.Model):
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.CASCADE, related_name='prescriptions'
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='issued_prescriptions'
    )
    diagnosis   = models.TextField()
    medications = models.TextField(help_text="List of prescribed medicines with dosage")
    notes       = models.TextField(blank=True, null=True)
    prescription_date = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['patient', '-prescription_date']),
            models.Index(fields=['doctor',  '-prescription_date']),
        ]
        ordering = ['-prescription_date']

    def __str__(self):
        return f"Prescription for {self.patient.patient_id} by Dr. {self.doctor.get_full_name()}"
