from rest_framework import serializers
from apps.audit.models import ActivityFlag, ActivitySettings, AuditLog, SuspiciousAlert
from apps.audit.reason_text import describe, flag_severity

class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    role = serializers.CharField(source='user.role', read_only=True)

    class Meta:
        model = AuditLog
        fields = ('id', 'user', 'username', 'role', 'action', 'description', 'timestamp', 'ip_address', 'patient')
        read_only_fields = fields


class ActivityFlagSerializer(serializers.ModelSerializer):
    """A flagged user's activity; only status and note can be changed (by an admin reviewing it)."""
    username = serializers.CharField(source='user.username', read_only=True)
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    role = serializers.CharField(source='user.role', read_only=True)
    reviewed_by_username = serializers.CharField(source='reviewed_by.username', read_only=True, default=None)
    # Worded from the stored numbers on every read, so older flags show the same plain text.
    reasons = serializers.SerializerMethodField()
    severity = serializers.SerializerMethodField()

    class Meta:
        model = ActivityFlag
        fields = (
            'id', 'user', 'username', 'full_name', 'role', 'window_start', 'window_end',
            'features', 'reasons', 'severity', 'eps', 'status', 'reviewed_by', 'reviewed_by_username', 'note',
            'created_at',
        )
        read_only_fields = tuple(f for f in fields if f not in ('status', 'note'))

    def get_reasons(self, obj) -> list[dict]:
        return [describe(r, obj.user.role) for r in obj.reasons]

    def get_severity(self, obj) -> str:
        return flag_severity(obj.reasons)


class ActivitySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivitySettings
        fields = ('activity_window_days', 'dbscan_eps', 'dbscan_min_samples', 'updated_at')
        read_only_fields = ('updated_at',)


class ActivityAnalysisParamsSerializer(serializers.Serializer):
    """Parameters for one analysis run; anything left out comes from ActivitySettings."""
    role = serializers.ChoiceField(choices=['ADMIN', 'DOCTOR', 'PATIENT'], default='DOCTOR')
    days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    eps = serializers.FloatField(min_value=0.01, max_value=100.0, required=False)
    min_samples = serializers.IntegerField(min_value=2, max_value=100, required=False)
    demo = serializers.BooleanField(default=False)
    # auto: use the suggested eps and min_samples for this role's users instead of eps/min_samples.
    auto = serializers.BooleanField(default=False)
    # POST only: save flags just for these users (each must still be an outlier in this run).
    user_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=False)


class SuspiciousAlertSerializer(serializers.ModelSerializer):
    """A suspicious user-day; only status can be changed (by an admin reviewing it)."""
    username = serializers.CharField(source='user.username', read_only=True)
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    role = serializers.CharField(source='user.role', read_only=True)

    class Meta:
        model = SuspiciousAlert
        fields = ('id', 'user', 'username', 'full_name', 'role', 'day', 'reason', 'features', 'status', 'created_at')
        read_only_fields = tuple(f for f in fields if f != 'status')
