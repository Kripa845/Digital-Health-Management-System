import uuid
from django.db import models
from django.conf import settings
from apps.patients.models import Patient
from apps.doctors.models import Doctor

class Appointment(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ACCEPTED', 'Accepted'),
        ('DECLINED', 'Declined'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='appointments')
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='appointments')
    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    reason = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_appointments')
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['patient', 'appointment_date', 'status']),
            models.Index(fields=['doctor', 'appointment_date', 'status']),
            models.Index(fields=['status', 'appointment_date']),
        ]
        constraints = [
            # One live booking per doctor slot, enforced by the database so two
            # simultaneous requests cannot both succeed.
            models.UniqueConstraint(
                fields=['doctor', 'appointment_date', 'appointment_time'],
                condition=models.Q(status__in=['PENDING', 'ACCEPTED']),
                name='unique_active_doctor_slot',
            ),
        ]
        ordering = ['-appointment_date', '-appointment_time']

    def __str__(self):
        return f"Appointment {self.id} - {self.patient} with {self.doctor} on {self.appointment_date}"
