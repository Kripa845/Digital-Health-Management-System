import os
from django.db import models
from django.core.exceptions import ValidationError


def validate_lab_report_file(value):
    ext = os.path.splitext(value.name)[1].lower()
    valid_extensions = ['.pdf', '.png', '.jpg', '.jpeg']
    if ext not in valid_extensions:
        raise ValidationError('Unsupported file type. Allowed: PDF, PNG, JPG, JPEG.')
    if value.size > 10 * 1024 * 1024:
        raise ValidationError('File size exceeds the 10MB limit.')


class LabReport(models.Model):

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    patient = models.ForeignKey(
        'patients.Patient',
        on_delete=models.CASCADE,
        related_name='lab_reports',
    )
   
    file = models.FileField(
        upload_to='lab_reports/',
        validators=[validate_lab_report_file],
    )
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

   
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    error_message = models.TextField(blank=True)

    
    ocr_text = models.TextField(blank=True)

    
    detected_count = models.PositiveSmallIntegerField(default=0)
    updated_count = models.PositiveSmallIntegerField(default=0)
    unchanged_count = models.PositiveSmallIntegerField(default=0)

    processed_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.file and self.file.name:
            ext = os.path.splitext(self.file.name)[1].lower().replace('.', '')
            self.file_type = ext.upper()
            if not self.name:
                self.name = os.path.basename(self.file.name)
            try:
                self.size = self.file.size
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"LabReport({self.id}) – {self.name} – {self.patient.patient_id}"

    class Meta:
        ordering = ['-uploaded_at']


class LabReportField(models.Model):
  
    class ChangeStatus(models.TextChoices):
        INSERTED = 'INSERTED', 'Inserted'   
        UPDATED = 'UPDATED', 'Updated'       
        UNCHANGED = 'UNCHANGED', 'Unchanged' 

    report = models.ForeignKey(
        LabReport,
        on_delete=models.CASCADE,
        related_name='fields',
    )

    field_name = models.CharField(max_length=100)
    
    patient_field = models.CharField(max_length=100, blank=True)

    extracted_value = models.CharField(max_length=255)
    previous_value = models.CharField(max_length=255, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    reference_range = models.CharField(max_length=100, blank=True)

    change_status = models.CharField(
        max_length=10,
        choices=ChangeStatus.choices,
        default=ChangeStatus.UNCHANGED,
    )

    def __str__(self):
        return f"{self.field_name}: {self.extracted_value} ({self.change_status})"

    class Meta:
        ordering = ['field_name']
