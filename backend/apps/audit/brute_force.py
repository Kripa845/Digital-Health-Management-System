"""Rule-based brute-force check, run on every failed login alongside DBSCAN.

DBSCAN (detect_suspicious) needs a couple of weeks of history and runs once a
day, so a burst of failed logins could go unnoticed until then, or forever on a
small system. This rule needs no history: BRUTE_FORCE_MAX_FAILED_LOGINS failed
logins for one account within BRUTE_FORCE_WINDOW_MINUTES (both in settings,
default 5 in 10 minutes) store a SuspiciousAlert for that user and day straight
away. Admins are notified when the alert is first created; further failures
that day update its count, and reopen it (NEW, notified again) if an admin had
already reviewed or dismissed it, since the attack is still going on. Nothing here blocks or changes the account.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.audit.models import AuditLog, SuspiciousAlert
from apps.audit.suspicious import FAILED_LOGIN
from apps.audit.suspicious_service import save_alerts


def check_failed_logins(user, now=None) -> SuspiciousAlert | None:
    """Alert on `user` if the recent failed logins reach the threshold; the alert, or None."""
    now = now or timezone.now()
    threshold = settings.BRUTE_FORCE_MAX_FAILED_LOGINS
    minutes = settings.BRUTE_FORCE_WINDOW_MINUTES
    failures = AuditLog.objects.filter(
        user=user, action=FAILED_LOGIN, timestamp__gt=now - timedelta(minutes=minutes),
    ).count()
    if failures < threshold:
        return None
    day = timezone.localdate(now)
    save_alerts([{
        'user_id': user.pk,
        'features': {f'failed_logins_{minutes}min': failures},
        'reason': f'failed logins in {minutes} min = {failures} (threshold {threshold})',
    }], day, reopen=True)
    return SuspiciousAlert.objects.get(user=user, day=day)
