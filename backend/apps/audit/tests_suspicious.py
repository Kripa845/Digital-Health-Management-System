"""Tests for suspicious-day detection: seed_demo_audit, detect_suspicious, the brute-force rule and the alerts API."""
from datetime import timedelta
from io import StringIO

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog, SuspiciousAlert
from apps.audit.management.commands.seed_demo_audit import ADMIN_USERNAME, ATTACKERS, PREFIX
from apps.audit.suspicious_service import save_alerts
from apps.notifications.models import Notification
from apps.users.factories import make_admin, make_doctor, make_patient

ALERTS_URL = '/api/v1/suspicious-alerts/'


def run(command, *args):
    out = StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


class SeededTestCase(TestCase):
    """14 days of normal demo activity, seeded once; each test's attack is rolled back."""

    @classmethod
    def setUpTestData(cls):
        run('seed_demo_audit')

    def alert_users(self):
        return sorted(SuspiciousAlert.objects.values_list('user__username', flat=True))


class NormalActivityTests(SeededTestCase):
    def test_normal_data_has_no_alerts(self):
        out = run('detect_suspicious')
        self.assertIn('DOCTOR: 12 user-days checked', out)
        self.assertIn('0 alerts created', out)
        self.assertEqual(SuspiciousAlert.objects.count(), 0)

    def test_seeded_rows_are_marked_as_demo(self):
        self.assertFalse(AuditLog.objects.exclude(description__startswith='[DEMO] ').exists())
        self.assertFalse(AuditLog.objects.exclude(user__username__startswith=PREFIX).exists())


class AttackTests(SeededTestCase):
    def check_attack(self, kind, expected_feature):
        run('seed_demo_audit', '--attack', kind)
        out = run('detect_suspicious')
        username = f'{PREFIX}{ATTACKERS[kind]}'
        self.assertEqual(self.alert_users(), [username])
        alert = SuspiciousAlert.objects.get()
        self.assertIn(expected_feature, alert.reason)
        self.assertIn('normal about', alert.reason)
        self.assertIn(f'ALERT {username}', out)
        self.assertTrue(Notification.objects.filter(receiver__username=ADMIN_USERNAME,
                                                    title__contains=username).exists())

    def test_brute_force(self):
        self.check_attack('brute_force', 'failed_logins = 25 (normal about 0)')

    def test_snooping(self):
        self.check_attack('snooping', 'distinct_patients')

    def test_export(self):
        self.check_attack('export', 'records_viewed')

    def test_rerun_does_not_duplicate_and_keeps_review(self):
        run('seed_demo_audit', '--attack', 'brute_force')
        run('detect_suspicious')
        SuspiciousAlert.objects.update(status=SuspiciousAlert.Status.REVIEWED)
        out = run('detect_suspicious')
        self.assertIn('0 alerts created, 1 updated', out)
        self.assertEqual(SuspiciousAlert.objects.count(), 1)
        self.assertEqual(SuspiciousAlert.objects.get().status, SuspiciousAlert.Status.REVIEWED)
        self.assertEqual(Notification.objects.filter(receiver__username=ADMIN_USERNAME).count(), 1)

    def test_reset_removes_only_demo_rows(self):
        admin = make_admin('realadmin')
        AuditLog.objects.create(user=admin, action='LOGIN', description='real')
        run('seed_demo_audit', '--reset')
        self.assertEqual(list(AuditLog.objects.values_list('description', flat=True)), ['real'])
        self.assertEqual(SuspiciousAlert.objects.count(), 0)


class TooLittleDataTests(TestCase):
    def test_exits_cleanly(self):
        admin = make_admin()
        for _ in range(5):
            AuditLog.objects.create(user=admin, action='LOGIN', description='login')
        out = run('detect_suspicious')
        self.assertIn('Not enough activity', out)
        self.assertIn('1 user-days', out)
        self.assertEqual(SuspiciousAlert.objects.count(), 0)

    def test_empty_log(self):
        self.assertIn('0 user-days', run('detect_suspicious'))

    def test_seeder_refuses_database_with_real_patients(self):
        make_patient()
        with self.assertRaises(CommandError):
            run('seed_demo_audit')


class AlertApiTests(SeededTestCase):
    def setUp(self):
        run('seed_demo_audit', '--attack', 'export')
        run('detect_suspicious')
        self.alert = SuspiciousAlert.objects.get()
        self.client = APIClient()

    def test_only_admins_can_see_alerts(self):
        self.client.force_authenticate(make_patient().user)
        self.assertEqual(self.client.get(ALERTS_URL).status_code, 403)
        self.client.force_authenticate(make_admin())
        data = self.client.get(ALERTS_URL, {'status': 'NEW'}).json()
        rows = data['results'] if isinstance(data, dict) else data
        self.assertEqual([r['username'] for r in rows], [f'{PREFIX}doc11'])

    def test_review_changes_status_only_and_is_logged(self):
        admin = make_admin()
        self.client.force_authenticate(admin)
        resp = self.client.patch(f'{ALERTS_URL}{self.alert.id}/', {'status': 'DISMISSED', 'reason': 'x'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, 'DISMISSED')
        self.assertNotEqual(self.alert.reason, 'x')
        self.assertTrue(AuditLog.objects.filter(user=admin, action='REVIEW_SUSPICIOUS_ALERT').exists())


class DetectApiTests(SeededTestCase):
    """POST /suspicious-alerts/detect/ runs DBSCAN from the page, no scheduled job needed."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.force_authenticate(make_admin())

    def detect(self, **body):
        return self.client.post(f'{ALERTS_URL}detect/', body, format='json')

    def test_only_admins_can_run_detection(self):
        self.client.force_authenticate(make_patient().user)
        self.assertEqual(self.detect().status_code, 403)

    def test_attack_today_creates_alert(self):
        run('seed_demo_audit', '--attack', 'brute_force')
        resp = self.detect()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['created'], 1)
        self.assertEqual(self.alert_users(), [f'{PREFIX}{ATTACKERS["brute_force"]}'])

    def test_recent_run_is_reused_unless_forced(self):
        self.assertEqual(self.detect().json()['created'], 0)
        run('seed_demo_audit', '--attack', 'snooping')
        self.assertEqual(self.detect().json()['created'], 0)          # cached run, DBSCAN not re-run
        self.assertEqual(self.detect(force=True).json()['created'], 1)


LOGIN_URL = '/api/v1/auth/login/'
PASSWORD = 'Str0ng-pass-123'      # the factories' password


@override_settings(SECURE_SSL_REDIRECT=False, BRUTE_FORCE_MAX_FAILED_LOGINS=5, BRUTE_FORCE_WINDOW_MINUTES=10)
class BruteForceRuleTests(TestCase):
    """Failed logins through the real login endpoint, mixed with normal traffic."""

    def setUp(self):
        cache.clear()       # login rate limit
        self.admin = make_admin()
        self.target = make_patient('victim').user
        self.normal = [make_patient('pat2', phone='9800000003').user, make_doctor('doc1').user]

    def login(self, username, password, ip='192.0.2.1'):
        return APIClient().post(LOGIN_URL, {'username': username, 'password': password},
                                format='json', REMOTE_ADDR=ip)

    def fail(self, n, username='victim'):
        for _ in range(n):
            self.assertEqual(self.login(username, 'wrong-password', ip='203.0.113.66').status_code, 401)

    def normal_traffic(self):
        for i, user in enumerate(self.normal):
            ip = f'198.51.100.{10 + i}'
            self.assertEqual(self.login(user.username, 'typo', ip).status_code, 401)      # one honest typo
            self.assertEqual(self.login(user.username, PASSWORD, ip).status_code, 200)

    def admin_notifications(self):
        return Notification.objects.filter(receiver=self.admin, title__startswith='Suspicious activity')

    def test_repeated_failures_raise_one_alert_and_one_notification(self):
        self.normal_traffic()
        self.fail(7)
        alert = SuspiciousAlert.objects.get()
        self.assertEqual(alert.user, self.target)
        self.assertEqual(alert.day, timezone.localdate())
        self.assertEqual(alert.reason, 'failed logins in 10 min = 7 (threshold 5)')
        self.assertEqual(alert.features, {'failed_logins_10min': 7})
        self.assertEqual(self.admin_notifications().count(), 1)      # created at the 5th failure, not repeated
        self.assertIn('victim', self.admin_notifications().get().title)

    def test_below_threshold_raises_nothing(self):
        self.normal_traffic()
        self.fail(4)
        self.assertFalse(SuspiciousAlert.objects.exists())
        self.assertFalse(self.admin_notifications().exists())

    def test_failures_outside_the_window_do_not_count(self):
        self.fail(4)
        AuditLog.objects.filter(action='LOGIN_FAILED').update(timestamp=timezone.now() - timedelta(minutes=11))
        self.fail(1)
        self.assertFalse(SuspiciousAlert.objects.exists())
        self.fail(4)
        self.assertTrue(SuspiciousAlert.objects.filter(user=self.target).exists())

    @override_settings(BRUTE_FORCE_MAX_FAILED_LOGINS=3, BRUTE_FORCE_WINDOW_MINUTES=2)
    def test_threshold_comes_from_settings(self):
        self.fail(3)
        self.assertEqual(SuspiciousAlert.objects.get().reason, 'failed logins in 2 min = 3 (threshold 3)')

    def test_new_burst_reopens_dismissed_alert_and_notifies_again(self):
        self.fail(5)
        SuspiciousAlert.objects.update(status=SuspiciousAlert.Status.DISMISSED)
        self.fail(1)
        alert = SuspiciousAlert.objects.get()
        self.assertEqual(alert.status, SuspiciousAlert.Status.NEW)
        self.assertEqual(alert.reason, 'failed logins in 10 min = 6 (threshold 5)')
        self.assertEqual(self.admin_notifications().count(), 2)
        self.fail(1)                                    # still NEW: no third notification
        self.assertEqual(self.admin_notifications().count(), 2)

    def test_reviewed_alert_keeps_status_and_dbscan_reason_is_merged(self):
        self.fail(5)
        alert = SuspiciousAlert.objects.get()
        alert.status = SuspiciousAlert.Status.REVIEWED
        alert.save()
        save_alerts([{'user_id': self.target.pk, 'features': {'failed_logins': 6.0},
                      'reason': 'failed_logins = 6 (normal about 0); events = 6 (normal about 3)'}], alert.day)
        alert.refresh_from_db()
        self.assertEqual(alert.status, SuspiciousAlert.Status.REVIEWED)       # a DBSCAN re-run keeps the review
        self.fail(1)
        alert.refresh_from_db()
        self.assertEqual(alert.status, SuspiciousAlert.Status.NEW)            # a new burst reopens it
        self.assertEqual(alert.reason, 'failed logins in 10 min = 6 (threshold 5); '
                                       'failed_logins = 6 (normal about 0); events = 6 (normal about 3)')
        self.assertEqual(alert.features, {'failed_logins_10min': 6, 'failed_logins': 6.0})
        self.assertEqual(self.admin_notifications().count(), 2)
