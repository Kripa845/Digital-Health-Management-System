from django.db import models
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator

class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=50, db_index=True)
    description = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    # The patient whose record the action opened, when there is one.
    patient = models.ForeignKey('patients.Patient', on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')

    class Meta:
        indexes = [
            models.Index(fields=['-timestamp', 'action']),
            models.Index(fields=['user', '-timestamp']),
        ]

    def save(self, *args, **kwargs):
        # Append-only: an entry can be written once and never changed.
        if self.pk is not None and not self._state.adding:
            raise PermissionError('Audit log entries cannot be modified.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Audit log entries cannot be deleted.')

    def __str__(self):
        user_str = self.user.username if self.user else "Anonymous"
        return f"{user_str} - {self.action} at {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"


class ActivityFlag(models.Model):
    """A user whose activity in a time window stood out from others with the same role.

    Written by the flag_activity_anomalies command (DBSCAN noise point) for an
    administrator to review. A flag never blocks, locks or changes the account.
    """
    class Status(models.TextChoices):
        NEW = 'NEW', 'New'
        REVIEWED = 'REVIEWED', 'Reviewed'
        DISMISSED = 'DISMISSED', 'Dismissed'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='activity_flags')
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    features = models.JSONField(default=dict)
    reasons = models.JSONField(default=list)
    eps = models.FloatField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_activity_flags',
    )
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'window_start', 'window_end'], name='unique_activity_flag_window'),
        ]

    def __str__(self):
        return f"Activity flag: {self.user.username} {self.window_start:%Y-%m-%d}..{self.window_end:%Y-%m-%d} ({self.status})"


class ActivitySettings(models.Model):
    """Settings for activity anomaly flagging (a single row, pk=1)."""
    activity_window_days = models.PositiveIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(365)])
    dbscan_eps = models.FloatField(
        default=1.0, validators=[MinValueValidator(0.01), MaxValueValidator(100.0)])
    dbscan_min_samples = models.PositiveIntegerField(
        default=5, validators=[MinValueValidator(2), MaxValueValidator(100)])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'activity settings'
        verbose_name_plural = 'activity settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> 'ActivitySettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'Activity settings ({self.activity_window_days} days, eps {self.dbscan_eps:g}, min {self.dbscan_min_samples})'


class SuspiciousAlert(models.Model):
    """One user's day of activity that DBSCAN found unlike the recent normal days.

    Written by the detect_suspicious command for an administrator to review.
    An alert never blocks, locks or changes the account.
    """
    class Status(models.TextChoices):
        NEW = 'NEW', 'New'
        REVIEWED = 'REVIEWED', 'Reviewed'
        DISMISSED = 'DISMISSED', 'Dismissed'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='suspicious_alerts')
    day = models.DateField(db_index=True)
    reason = models.TextField()
    features = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-day', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'day'], name='unique_suspicious_alert_user_day'),
        ]

    def __str__(self):
        return f"Suspicious alert: {self.user.username} on {self.day} ({self.status})"
