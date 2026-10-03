from django.db import models
from django.core.exceptions import ValidationError
import os
import uuid

def validate_file_extension_and_size(value):
    ext = os.path.splitext(value.name)[1].lower()
    valid_extensions = ['.pdf', '.png', '.jpg', '.jpeg']
    if ext not in valid_extensions:
        raise ValidationError('Unsupported file extension. Allowed extensions are: PDF, PNG, JPG, JPEG.')

    if value.size > 5 * 1024 * 1024:
        raise ValidationError('File size exceeds the 5MB limit.')

def document_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f'patient_documents/{uuid.uuid4().hex}{ext}'


class Document(models.Model):
    REPORT_TYPE_CHOICES = [
        ('MEDICAL', 'Medical Report'),
        ('ADDITIONAL', 'Additional Report'),
    ]
    patient = models.ForeignKey('patients.Patient', on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to=document_upload_path, validators=[validate_file_extension_and_size])
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10, blank=True)
    size = models.IntegerField(help_text="File size in bytes", blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    report_type = models.CharField(max_length=10, choices=REPORT_TYPE_CHOICES, default='ADDITIONAL')
    uploaded_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='uploaded_documents')

    def save(self, *args, **kwargs):
        if self.file:
            self.size = self.file.size
            ext = os.path.splitext(self.file.name)[1].lower().replace('.', '')
            self.file_type = ext.upper()
            if not self.name:
                self.name = os.path.basename(self.file.name)[:255]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.file_type}) - Patient: {self.patient.patient_id}"
