"""Database side of suspicious-day detection, shared by detect_suspicious, plot_suspicious and the alerts API.

Loads audit entries for the checked day plus its history (timestamps in local
time) and stores suspicious user-days as SuspiciousAlert rows. Alerts never change an account.
"""
from datetime import date, datetime, time, timedelta

import pandas as pd
from django.utils import timezone

from apps.audit.models import AuditLog, SuspiciousAlert
from apps.audit.suspicious import EPS, MIN_ROWS, MIN_SAMPLES, build_daily, check
from apps.notifications.models import Notification
from apps.users.models import User


def load_daily(day: date, history: int) -> pd.DataFrame:
    """User-day features from local midnight `history` days before `day` to the end of `day`."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day - timedelta(days=history), time.min), tz)
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)
    events = pd.DataFrame([
        {'user_id': e['user_id'], 'role': e['user__role'], 'action': e['action'],
         'timestamp': timezone.localtime(e['timestamp'], tz).replace(tzinfo=None),   # local clock hours
         'patient_id': e['patient_id'], 'ip_address': e['ip_address']}
        for e in AuditLog.objects.filter(
            user__isnull=False, timestamp__gte=start, timestamp__lt=end,
        ).values('user_id', 'user__role', 'action', 'timestamp', 'patient_id', 'ip_address').iterator()
    ])
    return build_daily(events)


def run_detection(day: date, history: int = 14) -> dict:
    """Run DBSCAN for every role on `day` and store the alerts; a summary for the command and the API.

    roles: one entry per role that had activity, with 'skipped' and its 'message'
    when DBSCAN could not run (too few user-days to learn what is normal).
    """
    daily = load_daily(day, history)
    summary = {'day': day, 'history': history, 'eps': EPS, 'min_samples': MIN_SAMPLES,
               'min_rows': MIN_ROWS, 'user_days': len(daily), 'enough_data': len(daily) >= MIN_ROWS,
               'checked': 0, 'clusters': 0, 'created': 0, 'updated': 0, 'roles': [], 'alerts': []}
    if not summary['enough_data']:
        return summary
    for role in User.Role.values:
        result = check(daily, day, role)
        if result.n_rows == 0:
            continue
        summary['roles'].append({'role': role, 'user_days': result.n_rows, 'checked': result.n_checked,
                                 'clusters': result.n_clusters, 'suspicious': len(result.alerts),
                                 'skipped': result.skipped, 'message': result.message})
        if result.skipped:
            continue
        summary['checked'] += result.n_checked
        summary['clusters'] += result.n_clusters
        summary['alerts'] += result.alerts
        c, u = save_alerts(result.alerts, day)
        summary['created'] += c
        summary['updated'] += u
    return summary


def save_alerts(alerts: list[dict], day: date, reopen: bool = False) -> tuple[int, int]:
    """Create or update one alert per user and day; a reviewed alert keeps its status unless `reopen`.

    DBSCAN and the brute-force rule can both alert on the same user-day, so an
    update merges reasons and features instead of replacing them. Every active
    admin gets an in-app notification the first time an alert is created, and
    again when `reopen` (a new brute-force burst) sets a reviewed or dismissed
    alert back to NEW. DBSCAN re-runs never reopen, so a review sticks.
    """
    created = updated = 0
    for alert in alerts:
        obj, was_created = SuspiciousAlert.objects.get_or_create(
            user_id=alert['user_id'], day=day,
            defaults={'reason': alert['reason'], 'features': alert['features']},
        )
        if was_created:
            notify_admins(obj)
            created += 1
            continue
        obj.reason = merge_reasons(obj.reason, alert['reason'])
        obj.features = {**obj.features, **alert['features']}
        fields = ['reason', 'features']
        reopened = reopen and obj.status != SuspiciousAlert.Status.NEW
        if reopened:
            obj.status = SuspiciousAlert.Status.NEW
            fields.append('status')
        obj.save(update_fields=fields)
        if reopened:
            notify_admins(obj)
        updated += 1
    return created, updated


def merge_reasons(old: str, new: str) -> str:
    """'; '-separated parts keyed by the text before ' = '; a part in `new` replaces the same key in `old`."""
    parts = {}
    for part in [*old.split('; '), *new.split('; ')]:
        if part:
            parts[part.split(' = ')[0]] = part
    return '; '.join(parts.values())


def notify_admins(alert: SuspiciousAlert) -> None:
    Notification.objects.bulk_create([
        Notification(receiver=admin, role='ADMIN',
                     title=f'Suspicious activity: {alert.user.username} on {alert.day:%Y-%m-%d}',
                     message=alert.reason)
        for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True)
    ])
