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
    # Years in practice; a benefit criterion when the symptom checker ranks doctors (TOPSIS).
    experience_years = models.PositiveIntegerField(default=0)
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

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_schedule = instance.__dict__.get('availability_schedule')
        return instance

    def save(self, *args, **kwargs):
        if not self.doctor_id:
            self.doctor_id = self.__class__.generate_doctor_id()
        if not self.uuid_token:
            self.uuid_token = uuid.uuid4()
        schedule_changed = (
            self._state.adding
            or self.availability_schedule != getattr(self, '_loaded_schedule', self.availability_schedule)
        )
        super().save(*args, **kwargs)
        # The JSON summary is what admin forms, ranking and seed data write;
        # keep the bookable weekly schedule rows in step with it.
        if schedule_changed:
            self.sync_schedules_from_json()
        self._loaded_schedule = self.availability_schedule

    def sync_schedules_from_json(self):
        """Mirror ``availability_schedule`` ({'Monday': '09:00-17:00', ...}) into
        DoctorSchedule rows. A weekday that is missing, 'closed' or unreadable
        deactivates its row; slot lengths are kept."""
        from apps.doctors.scheduling import parse_window

        schedule = self.availability_schedule if isinstance(self.availability_schedule, dict) else {}
        existing = {row.weekday: row for row in self.schedules.all()}
        for weekday, name in enumerate(WEEKDAY_NAMES):
            window = parse_window(schedule.get(name))
            row = existing.get(weekday)
            if window:
                if row is None:
                    DoctorSchedule.objects.create(
                        doctor=self, weekday=weekday, start_time=window[0], end_time=window[1],
                    )
                elif (row.start_time, row.end_time, row.is_active) != (*window, True):
                    row.start_time, row.end_time, row.is_active = *window, True
                    row.save(update_fields=['start_time', 'end_time', 'is_active'])
            elif row is not None and row.is_active:
                row.is_active = False
                row.save(update_fields=['is_active'])

    def sync_json_from_schedules(self):
        """Rewrite ``availability_schedule`` from the DoctorSchedule rows (used
        after the rows are edited directly, e.g. in the Django admin)."""
        schedule = {}
        for row in self.schedules.all():
            schedule[WEEKDAY_NAMES[row.weekday]] = (
                f"{row.start_time:%H:%M}-{row.end_time:%H:%M}" if row.is_active else 'closed'
            )
        if schedule != self.availability_schedule:
            self.availability_schedule = schedule
            self.save(update_fields=['availability_schedule'])

    def __str__(self):
        return (
            f"{self.doctor_id} - Dr. {self.user.first_name} {self.user.last_name}"
            f" ({self.department})"
        )


WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


class DoctorSchedule(models.Model):
    """One bookable window per doctor and weekday, cut into slots of ``slot_minutes``."""
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='schedules')
    weekday = models.PositiveSmallIntegerField(
        choices=[(i, name) for i, name in enumerate(WEEKDAY_NAMES)],
        help_text='0 = Monday … 6 = Sunday',
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['doctor', 'weekday']
        constraints = [
            models.UniqueConstraint(fields=['doctor', 'weekday'], name='unique_doctor_weekday_schedule'),
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F('start_time')),
                                   name='schedule_end_after_start'),
            models.CheckConstraint(condition=models.Q(slot_minutes__gte=5), name='schedule_slot_min_5'),
        ]

    def __str__(self):
        return f"{self.doctor.doctor_id} {self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class DoctorLeave(models.Model):
    """A whole day the doctor does not see patients, whatever the weekly schedule says."""
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='leaves')
    date = models.DateField()
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['date']
        constraints = [
            models.UniqueConstraint(fields=['doctor', 'date'], name='unique_doctor_leave_day'),
        ]

    def __str__(self):
        return f"{self.doctor.doctor_id} on leave {self.date}"


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
