from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework import mixins, viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from apps.audit.activity_anomaly import FEATURES, analyse, auto_params, demo_features, detect, explain
from apps.audit.activity_service import activity_window, alerts_in_window, load_features, save_flags, usernames
from apps.audit.suspicious_service import run_detection
from apps.audit.models import ActivityFlag, ActivitySettings, AuditLog, SuspiciousAlert
from apps.audit.serializers import (
    ActivityAnalysisParamsSerializer, ActivityFlagSerializer, ActivitySettingsSerializer, AuditLogSerializer,
    SuspiciousAlertSerializer,
)
from apps.audit.utils import log_activity
from apps.users.permissions import IsAdmin

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['action', 'user', 'patient']
    search_fields = ['description', 'action', 'user__username', 'ip_address']
    ordering_fields = ['timestamp']
    ordering = ['-timestamp']

    def get_queryset(self):
        return AuditLog.objects.all()


class ActivityFlagViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                          viewsets.GenericViewSet):
    """GET / PATCH /api/v1/activity-flags/   {"status": "REVIEWED", "note": "..."}

    Unusual activity found by flag_activity_anomalies, for admin review only:
    reviewing a flag records the decision and never changes the flagged account.
    """
    serializer_class = ActivityFlagSerializer
    permission_classes = [IsAdmin]
    http_method_names = ['get', 'patch', 'head', 'options']
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status', 'user', 'user__role']
    ordering_fields = ['created_at', 'window_end']
    ordering = ['-created_at']

    def get_queryset(self):
        return ActivityFlag.objects.select_related('user', 'reviewed_by')

    def perform_update(self, serializer):
        flag = serializer.save(reviewed_by=self.request.user)
        log_activity(self.request.user, 'REVIEW_ACTIVITY_FLAG',
                     f"Marked activity flag {flag.id} for {flag.user.username} as {flag.status}"
                     + (f": {flag.note}" if flag.note else '.'), self.request)


DETECT_CACHE_KEY = 'suspicious-alerts:last-detection'
DETECT_EVERY = timedelta(minutes=2)


class SuspiciousAlertViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                             viewsets.GenericViewSet):
    """GET / PATCH /api/v1/suspicious-alerts/   {"status": "REVIEWED"}

    Suspicious user-days found by detect_suspicious, for admin review only:
    reviewing an alert records the decision and never changes the account.
    """
    serializer_class = SuspiciousAlertSerializer
    permission_classes = [IsAdmin]
    http_method_names = ['get', 'patch', 'post', 'head', 'options']     # POST only for detect/
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status', 'user', 'day']
    ordering_fields = ['day', 'created_at']
    ordering = ['-day', '-created_at']

    def get_queryset(self):
        return SuspiciousAlert.objects.select_related('user')

    @action(detail=False, methods=['post'])
    def detect(self, request):
        """POST /api/v1/suspicious-alerts/detect/   {"force": true}

        Runs DBSCAN for today (as detect_suspicious does) so new alerts appear
        without a scheduled job. The page calls this while it is open; without
        force a run from the last DETECT_EVERY is reused instead of re-running.
        """
        force = str(request.data.get('force', '')).lower() in ('1', 'true')
        summary = cache.get(DETECT_CACHE_KEY)
        if force or summary is None or summary['day'] != timezone.localdate().isoformat():
            result = run_detection(timezone.localdate())
            summary = {k: v for k, v in result.items() if k != 'alerts'}
            summary['day'] = result['day'].isoformat()
            summary['ran_at'] = timezone.now().isoformat()
            cache.set(DETECT_CACHE_KEY, summary, DETECT_EVERY.total_seconds())
        return Response(summary)

    def perform_update(self, serializer):
        alert = serializer.save()
        log_activity(self.request.user, 'REVIEW_SUSPICIOUS_ALERT',
                     f"Marked suspicious alert {alert.id} for {alert.user.username} on {alert.day} as {alert.status}.",
                     self.request)


class ActivitySettingsView(APIView):
    """GET / PUT /api/v1/activity-settings/   window days, DBSCAN eps and min_samples."""
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(ActivitySettingsSerializer(ActivitySettings.load()).data)

    def put(self, request):
        serializer = ActivitySettingsSerializer(ActivitySettings.load(), data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        log_activity(request.user, 'UPDATE_ACTIVITY_SETTINGS',
                     f'Activity review settings updated: {obj.activity_window_days} days, '
                     f'eps {obj.dbscan_eps:g}, min samples {obj.dbscan_min_samples}.', request)
        return Response(serializer.data)


class ActivityAnalysisView(APIView):
    """GET  /api/v1/activity-analysis/?role=DOCTOR&days=30&eps=1&min_samples=5[&demo=true][&auto=true]
    POST /api/v1/activity-analysis/   {"role": "DOCTOR", "days": 30, "eps": 1, "min_samples": 5[, "user_ids": [7]]}

    GET shows every step of the DBSCAN analysis for one role (features, scaling,
    k-distance curve, clusters, reasons) and saves nothing; demo=true uses
    synthetic users instead of the audit log; auto=true picks eps and min_samples
    from the data (see auto_params). POST runs it on real data and stores the
    outliers (or only those in user_ids) as ActivityFlags. Neither ever changes an account.
    """
    permission_classes = [IsAdmin]

    def _params(self, data):
        params = ActivityAnalysisParamsSerializer(data=data)
        params.is_valid(raise_exception=True)
        p = params.validated_data
        conf = ActivitySettings.load()
        return (p['role'], p.get('days', conf.activity_window_days), p.get('eps', conf.dbscan_eps),
                p.get('min_samples', conf.dbscan_min_samples), p['demo'], p['auto'], p.get('user_ids'))

    def get(self, request):
        role, days, eps, min_samples, demo, auto, _ = self._params(request.query_params)
        window_start, window_end = activity_window(days)
        feats = demo_features(role) if demo else load_features(window_start, window_end)
        if auto:
            eps, min_samples = auto_params(feats, role, eps)
        result = analyse(feats, role, eps, min_samples)
        names = usernames(u['user_id'] for u in result['users'])
        for i, u in enumerate(result['users']):
            u['username'] = f'demo-user-{i + 1:02d}' if demo else names.get(u['user_id'], f"user {u['user_id']}")
        result.update(window_start=window_start, window_end=window_end, days=days, demo=demo, auto=auto,
                      suspicious_alerts=[] if demo else alerts_in_window(role, window_start, window_end))
        return Response(result)

    def post(self, request):
        role, days, eps, min_samples, demo, auto, user_ids = self._params(request.data)
        if demo:
            return Response({'demo': ['Demo data cannot be saved as flags.']}, status=status.HTTP_400_BAD_REQUEST)
        window_start, window_end = activity_window(days)
        feats = load_features(window_start, window_end)
        if auto:
            eps, min_samples = auto_params(feats, role, eps)
        result = detect(feats, role, eps, min_samples)
        # Users with a suspicious alert in this window can be sent too, even when DBSCAN
        # did not single them out (or could not run because the role has too few users).
        alerted = {a['user_id'] for a in alerts_in_window(role, window_start, window_end)}
        chosen = set(user_ids or [])
        extra = chosen & alerted - {f['user_id'] for f in result.flags}
        if result.skipped and not extra:
            return Response({'detail': f'DBSCAN was not run for {role}: {result.message}'}, status=status.HTTP_400_BAD_REQUEST)
        flags = result.flags if user_ids is None else [f for f in result.flags if f['user_id'] in chosen]
        group = feats[feats['role'] == role]
        flags += [{'user_id': uid, 'features': {name: int(group.at[uid, name]) for name in FEATURES},
                   'reasons': explain(group, uid)}
                  for uid in sorted(extra) if uid in group.index]
        created, updated = save_flags(flags, window_start, window_end, eps, reopen=True)
        log_activity(request.user, 'RUN_ACTIVITY_ANALYSIS',
                     f'Ran activity analysis for {role} ({days} days, eps {eps:g}, min samples {min_samples}): '
                     f'{len(flags)} of {result.n_users} users flagged.', request)
        return Response({'role': role, 'n_users': result.n_users, 'flagged': len(flags),
                         'created': created, 'updated': updated})
