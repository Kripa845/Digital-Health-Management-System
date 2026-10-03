import os
import uuid
from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.core.exceptions import ValidationError


def validate_lab_report_file(value):
    ext = os.path.splitext(value.name)[1].lower()
    valid_extensions = ['.pdf', '.png', '.jpg', '.jpeg']
    if ext not in valid_extensions:
        raise ValidationError('Unsupported file type. Allowed: PDF, PNG, JPG, JPEG.')
    if value.size > 10 * 1024 * 1024:
        raise ValidationError('File size exceeds the 10MB limit.')


def lab_report_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f'lab_reports/{uuid.uuid4().hex}{ext}'


def lab_report_storage():
    """Encrypted files are not images, so on Cloudinary they go to raw storage."""
    if settings.STORAGES['default']['BACKEND'].startswith('cloudinary_storage'):
        from cloudinary_storage.storage import RawMediaCloudinaryStorage
        return RawMediaCloudinaryStorage()
    from django.core.files.storage import default_storage
    return default_storage


class LabReport(models.Model):

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        # Identity verified; the preview waits for the user to confirm it.
        PENDING_CONFIRMATION = 'PENDING_CONFIRMATION', 'Awaiting confirmation'
        # The identity gate could not verify the report; an admin decides.
        NEEDS_REVIEW = 'NEEDS_REVIEW', 'Needs review'
        # An admin rejected it after review (the file is deleted).
        REJECTED = 'REJECTED', 'Rejected'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        # No health card values were found; waits for the user to save it as a document only.
        NO_VALUES_SAVEABLE = 'NO_VALUES_SAVEABLE', 'No values; can be saved as a document'
        # Saved as a document only: the file is kept, no values or history rows were written.
        SAVED_NO_VALUES = 'SAVED_NO_VALUES', 'Saved without card values'
        FAILED = 'FAILED', 'Failed'

    patient = models.ForeignKey(
        'patients.Patient',
        on_delete=models.CASCADE,
        related_name='lab_reports',
    )

    file = models.FileField(
        upload_to=lab_report_upload_path,
        storage=lab_report_storage,
        validators=[validate_lab_report_file],
        blank=True,   # emptied when a rejected report's file is deleted
    )
    # SHA-256 of the uploaded bytes, so the same file is not processed twice.
    file_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    # True for files stored encrypted (every upload since encryption was added).
    is_encrypted = models.BooleanField(default=False)
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10, blank=True)
    size = models.PositiveIntegerField(help_text='File size in bytes', null=True, blank=True)

    uploaded_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_lab_reports',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Date printed on the report (collection/report date), when it could be read.
    report_date = models.DateField(null=True, blank=True)
    # Which label the date came from ('reporting', 'collection') or 'user' when typed in the preview.
    report_date_source = models.CharField(max_length=20, blank=True, default='')
    report_date_user_entered = models.BooleanField(default=False)
    # The name and age on the report matched the patient. The report's own
    # name and age are never stored.
    identity_verified = models.BooleanField(default=False)

    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    error_message = models.TextField(blank=True)

    # Structured data read from the report (see services/extractor.py); the
    # patient ID in it is masked and the report's raw text is never stored.
    extracted_json = models.JSONField(default=dict, blank=True)
    # Mean OCR confidence 0–100 (100 for selectable PDF text).
    ocr_confidence = models.FloatField(null=True, blank=True)
    # Why the identity gate sent the report for review (codes, see services/verifier.py).
    review_reasons = models.JSONField(default=list, blank=True)
    reviewed_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_lab_reports',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    detected_count = models.PositiveSmallIntegerField(default=0)
    updated_count = models.PositiveSmallIntegerField(default=0)
    unchanged_count = models.PositiveSmallIntegerField(default=0)

    processed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_lab_reports',
    )

    def save(self, *args, **kwargs):
        # Encrypted files are stored as ".enc", so type and size describe the
        # original upload and are set by the view; fill them only when missing.
        if self.file and self.file.name:
            if not self.file_type:
                ext = os.path.splitext(self.file.name)[1].lower().replace('.', '')
                self.file_type = ext.upper()
            if not self.name:
                self.name = os.path.basename(self.file.name)
            if self.size is None:
                try:
                    self.size = self.file.size
                except Exception:
                    pass
        super().save(*args, **kwargs)

    @property
    def effective_date(self):
        """The date the values were measured: the report date, else the upload date."""
        return self.report_date or self.uploaded_at.date()

    def __str__(self):
        return f"LabReport({self.id}) – {self.name} – {self.patient.patient_id}"

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [models.Index(fields=['patient', 'report_date'], name='labreport_patient_date')]
        constraints = [
            models.UniqueConstraint(
                fields=['patient', 'file_hash'],
                condition=~models.Q(file_hash=''),
                name='unique_lab_report_file_per_patient',
            ),
        ]


@receiver(post_delete, sender=LabReport)
def _delete_lab_report_file(sender, instance, **kwargs):
    """Remove the stored file with its report, so deleted uploads leave nothing behind."""
    if instance.file:
        instance.file.delete(save=False)


class LabReportField(models.Model):

    class ChangeStatus(models.TextChoices):
        INSERTED = 'INSERTED', 'Inserted'
        UPDATED = 'UPDATED', 'Updated'
        UNCHANGED = 'UNCHANGED', 'Unchanged'
        SKIPPED = 'SKIPPED', 'Needs review (not saved)'
        # Saved in the history only: a newer report already set the current value.
        HISTORY = 'HISTORY', 'Saved to history'

    report = models.ForeignKey(
        LabReport,
        on_delete=models.CASCADE,
        related_name='fields',
    )

    field_name = models.CharField(max_length=100)

    patient_field = models.CharField(max_length=100, blank=True)

    # As printed on the report.
    extracted_value = models.CharField(max_length=255)
    unit = models.CharField(max_length=50, blank=True)
    # In the unit the dashboard uses (equal to extracted_value when no conversion was needed).
    converted_value = models.CharField(max_length=50, blank=True)
    converted_unit = models.CharField(max_length=20, blank=True)

    previous_value = models.CharField(max_length=255, blank=True)
    reference_range = models.CharField(max_length=100, blank=True)

    change_status = models.CharField(
        max_length=10,
        choices=ChangeStatus.choices,
        default=ChangeStatus.UNCHANGED,
    )
    # Why a value was not (or will not be) saved; shown to the user.
    skip_reason = models.CharField(max_length=255, blank=True)
    # Machine-readable reason (out_of_range, unknown_unit, invalid,
    # blood_group_conflict, too_large); out_of_range values can be accepted on confirm.
    flag = models.CharField(max_length=24, blank=True)

    def __str__(self):
        return f"{self.field_name}: {self.extracted_value} ({self.change_status})"

    class Meta:
        ordering = ['field_name']


class LabResult(models.Model):
    """One confirmed, dated test value. A new row is written for every confirmed
    report, so the full history is kept; the patient record holds the latest."""

    patient = models.ForeignKey('patients.Patient', on_delete=models.CASCADE, related_name='lab_results')
    report = models.ForeignKey(LabReport, on_delete=models.CASCADE, related_name='results')
    test_name = models.CharField(max_length=50)            # patient field key, e.g. "hemoglobin"
    value = models.CharField(max_length=32)                # as stored, e.g. "13.40" or "120/80"
    value_numeric = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    report_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-report_date', '-id']
        indexes = [models.Index(fields=['patient', 'test_name', 'report_date'], name='labresult_patient_test_date')]

    def __str__(self):
        return f"{self.test_name}={self.value} ({self.report_date})"
