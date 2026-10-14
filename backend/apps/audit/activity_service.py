"""Database side of activity anomaly flagging, shared by the command and the admin API.

Loads audit events and access requests for a window (timestamps in local time),
and stores DBSCAN noise points as ActivityFlag rows. Flags never change an account.
"""
from datetime import datetime, time, timedelta

import pandas as pd
from django.utils import timezone

from apps.audit.activity_anomaly import build_features
from apps.audit.models import ActivityFlag, AuditLog, SuspiciousAlert
from apps.audit.reason_text import describe
from apps.doctors.models import AccessRequest
from apps.notifications.models import Notification
from apps.users.models import User


def activity_window(days: int) -> tuple[datetime, datetime]:
    """The last `days` days ending at the next local midnight, so reruns on one day share a window."""
    tz = timezone.get_current_timezone()
    end = timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=1), time.min), tz)
    return end - timedelta(days=days), end


def load_features(window_start: datetime, window_end: datetime) -> pd.DataFrame:
    tz = timezone.get_current_timezone()
    events = pd.DataFrame([
        {'user_id': e['user_id'], 'role': e['user__role'], 'action': e['action'],
         'timestamp': timezone.localtime(e['timestamp'], tz).replace(tzinfo=None),   # local clock hours
         'patient_id': e['patient_id']}
        for e in AuditLog.objects.filter(
            user__isnull=False, timestamp__gte=window_start, timestamp__lt=window_end,
        ).values('user_id', 'user__role', 'action', 'timestamp', 'patient_id').iterator()
    ])
    requests = pd.DataFrame([
        {'user_id': r['doctor__user_id'], 'role': r['doctor__user__role'], 'status': r['status']}
        for r in AccessRequest.objects.filter(
            created_at__gte=window_start, created_at__lt=window_end,
        ).values('doctor__user_id', 'doctor__user__role', 'status').iterator()
    ])
    return build_features(events, requests)


def save_flags(flags: list[dict], window_start: datetime, window_end: datetime, eps: float,
               reopen: bool = False) -> tuple[int, int]:
    """Create or update one flag per user and window; a reviewed flag keeps its status and note unless `reopen`.

    `reopen` is for an admin sending a user for review from the analysis page:
    a reviewed or dismissed flag for the same window goes back to NEW, so it is
    listed under Unusual activity again. Every active admin gets an in-app
    notification when a flag is created or reopened.
    """
    created = updated = 0
    for flag in flags:
        obj, was_created = ActivityFlag.objects.update_or_create(
            user_id=flag['user_id'], window_start=window_start, window_end=window_end,
            defaults={'features': flag['features'], 'reasons': flag['reasons'], 'eps': eps},
        )
        reopened = reopen and not was_created and obj.status != ActivityFlag.Status.NEW
        if reopened:
            obj.status = ActivityFlag.Status.NEW
            obj.reviewed_by = None
            obj.save(update_fields=['status', 'reviewed_by'])
        if was_created or reopened:
            notify_admins(obj)
        created += was_created
        updated += not was_created
    return created, updated


def notify_admins(flag: ActivityFlag) -> None:
    Notification.objects.bulk_create([
        Notification(receiver=admin, role='ADMIN',
                     title=f'Unusual activity: {flag.user.username} ({flag.user.role.lower()})',
                     message=' '.join(describe(r, flag.user.role)['text'] for r in flag.reasons))
        for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True)
    ])


def alerts_in_window(role: str, window_start: datetime, window_end: datetime) -> list[dict]:
    """Suspicious alerts (failed-login rule or daily DBSCAN) for users of `role` on days inside the window."""
    first, last = timezone.localdate(window_start), timezone.localdate(window_end)
    return [
        {'id': a.id, 'user_id': a.user_id, 'username': a.user.username, 'full_name': a.user.get_full_name(),
         'day': a.day, 'reason': a.reason, 'status': a.status}
        for a in SuspiciousAlert.objects.select_related('user').filter(
            user__role=role, day__gte=first, day__lt=last).order_by('-day', '-created_at')
    ]


def usernames(user_ids) -> dict:
    return dict(User.objects.filter(id__in=[u for u in user_ids if u > 0]).values_list('id', 'username'))
