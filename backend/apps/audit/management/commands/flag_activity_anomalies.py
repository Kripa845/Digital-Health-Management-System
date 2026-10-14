"""Flag users whose recent activity stands out from others with the same role.

    python manage.py flag_activity_anomalies                  # settings from Admin Settings
    python manage.py flag_activity_anomalies --role DOCTOR --days 14 --dry-run
    python manage.py flag_activity_anomalies --kdist          # help choose --eps

Features per user come from the audit log and access requests (see
apps/audit/activity_anomaly.py); DBSCAN runs separately for each role and each
noise point is stored as an ActivityFlag for an administrator to review. Flags
never block, lock or change an account. The window ends at the next local
midnight, so running again on the same day updates the same flags.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.audit.activity_anomaly import detect, kdist_percentiles
from apps.audit.activity_service import activity_window, load_features, save_flags
from apps.audit.models import ActivitySettings
from apps.users.models import User


class Command(BaseCommand):
    help = 'Flag unusual per-user activity (DBSCAN per role) for admin review.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, help='Window length in days (default: Admin Settings).')
        parser.add_argument('--role', choices=User.Role.values, help='Only check this role.')
        parser.add_argument('--eps', type=float, help='DBSCAN neighbourhood radius (default: Admin Settings).')
        parser.add_argument('--min-samples', type=int, help='DBSCAN min_samples (default: Admin Settings).')
        parser.add_argument('--kdist', action='store_true',
                            help='Print k-distance percentiles per role to help choose --eps, then stop.')
        parser.add_argument('--dry-run', action='store_true', help='Print the flags without saving them.')

    def handle(self, *args, **opts):
        conf = ActivitySettings.load()
        days = opts['days'] or conf.activity_window_days
        eps = opts['eps'] if opts['eps'] is not None else conf.dbscan_eps
        min_samples = opts['min_samples'] or conf.dbscan_min_samples
        if days < 1 or eps <= 0 or min_samples < 2:
            raise CommandError('--days must be at least 1, --eps above 0 and --min-samples at least 2.')

        window_start, window_end = activity_window(days)
        feats = load_features(window_start, window_end)
        roles = [opts['role']] if opts['role'] else User.Role.values
        self.stdout.write(f'Window {window_start:%Y-%m-%d %H:%M} to {window_end:%Y-%m-%d %H:%M} '
                          f'({timezone.get_current_timezone()}), eps {eps:g}, min_samples {min_samples}, '
                          f'{len(feats)} active users.')

        if opts['kdist']:
            for role in roles:
                pct = kdist_percentiles(feats, role, min_samples)
                text = ', '.join(f'p{p} {d:g}' for p, d in pct.items()) if pct else 'not enough users'
                self.stdout.write(f'{role}: k-distance (k={min_samples - 1}) {text}')
            return

        created = updated = 0
        for role in roles:
            result = detect(feats, role, eps, min_samples)
            if result.skipped:
                self.stdout.write(f'{role}: skipped ({result.message})')
                continue
            self.stdout.write(f'{role}: {result.n_users} users, {len(result.flags)} flagged.')
            for flag in result.flags:
                summary = '; '.join(r['text'] for r in flag['reasons'])
                self.stdout.write(f'  user {flag["user_id"]}: {summary}')
            if not opts['dry_run']:
                c, u = save_flags(result.flags, window_start, window_end, eps)
                created += c
                updated += u

        if opts['dry_run']:
            self.stdout.write('Dry run: nothing saved.')
        else:
            self.stdout.write(self.style.SUCCESS(f'{created} new flags, {updated} updated.'))
