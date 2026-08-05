import uuid
from django.db import models
from django.conf import settings

class Notification(models.Model):
    ROLE_CHOICES = [
        ('ADMIN', 'Admin'),
        ('DOCTOR', 'Doctor'),
        ('PATIENT', 'Patient'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    related_appointment = models.ForeignKey('appointments.Appointment', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['receiver', '-created_at']),
            models.Index(fields=['role', 'read', '-created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.receiver.username}: {self.title}"
