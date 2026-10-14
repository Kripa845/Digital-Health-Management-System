"""Alert on user-days whose activity is unlike that role's normal recent days.

    python manage.py detect_suspicious                     # today, 14 days of history
    python manage.py detect_suspicious --day 2026-10-05 --history 14

Each user's activity on each day becomes one row of features (see
apps/audit/suspicious.py). DBSCAN runs separately for each role over the
history days plus the checked day; a checked-day row labelled noise (-1) is
stored as a SuspiciousAlert for an administrator to review. Running again for
the same day updates the same alerts. Alerts never change an account.

The admin Suspicious Alerts page also runs the same check for today every few
minutes while it is open (POST /api/v1/suspicious-alerts/detect/); scheduling
this command once a day (cron or Windows Task Scheduler, see the README) still
covers days nobody opens the page. Brute-force bursts are alerted on at login time by
apps/audit/brute_force.py and do not wait for this command.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.audit.suspicious import EPS, MIN_ROWS, MIN_SAMPLES
from apps.audit.suspicious_service import run_detection
from apps.users.models import User


class Command(BaseCommand):
    help = 'Alert on suspicious user-days (DBSCAN per role against recent normal days).'

    def add_arguments(self, parser):
        parser.add_argument('--day', type=date.fromisoformat, help='Day to check, YYYY-MM-DD (default: today).')
        parser.add_argument('--history', type=int, default=14, help='Days before --day that define normal (default 14).')

    def handle(self, *args, **opts):
        day = opts['day'] or timezone.localdate()
        if opts['history'] < 1:
            raise CommandError('--history must be at least 1.')
        summary = run_detection(day, opts['history'])
        self.stdout.write(f'Checking {day} against {opts["history"]} days of history '
                          f'(eps {EPS:g}, min_samples {MIN_SAMPLES}); {summary["user_days"]} user-days loaded.')
        if not summary['enough_data']:
            self.stdout.write(self.style.WARNING(
                f'Not enough activity to learn what is normal: {summary["user_days"]} user-days, at least {MIN_ROWS} '
                f'are needed. Nothing was checked.'))
            return

        names = dict(User.objects.filter(id__in=[a['user_id'] for a in summary['alerts']])
                     .values_list('id', 'username'))
        for role in summary['roles']:
            if role['skipped']:
                self.stdout.write(f'{role["role"]}: skipped ({role["message"]})')
                continue
            self.stdout.write(f'{role["role"]}: {role["checked"]} user-days checked, {role["clusters"]} clusters, '
                              f'{role["suspicious"]} suspicious.')
        for alert in summary['alerts']:
            self.stdout.write(self.style.ERROR(f'  ALERT {names.get(alert["user_id"])}: {alert["reason"]}'))

        self.stdout.write(self.style.SUCCESS(
            f'Summary: {summary["checked"]} rows checked, {summary["clusters"]} clusters found, '
            f'{summary["created"]} alerts created, {summary["updated"]} updated.'))
