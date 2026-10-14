"""Tests for activity anomaly flagging: the command, the admin endpoints and patient references."""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.activity_anomaly import Detection
from apps.audit.models import ActivityFlag, ActivitySettings, AuditLog, SuspiciousAlert
from apps.doctors.models import AccessRequest
from apps.notifications.models import Notification
from apps.patients.models import Patient
from apps.users.factories import make_admin, make_doctor, make_patient
from apps.users.models import User

FLAGS_URL = '/api/v1/activity-flags/'
SETTINGS_URL = '/api/v1/activity-settings/'


def run(*args):
    out = StringIO()
    call_command('flag_activity_anomalies', *args, stdout=out)
    return out.getvalue()


def make_flag(user, **extra):
    end = timezone.now()
    return ActivityFlag.objects.create(
        user=user, window_start=end - timedelta(days=30), window_end=end, eps=1.0,
        features={'distinct_patients': 40},
        reasons=[{'feature': 'distinct_patients', 'value': 40, 'median': 6.0, 'z': 12.0, 'text': '...'}], **extra)


class FlagCommandTests(TestCase):
    def test_empty_log(self):
        out = run()
        self.assertIn('0 active users', out)
        self.assertIn('DOCTOR: skipped', out)
        self.assertEqual(ActivityFlag.objects.count(), 0)

    def test_kdist_and_dry_run_save_nothing(self):
        run('--kdist')
        run('--dry-run', '--role', 'DOCTOR', '--days', '7', '--eps', '0.5', '--min-samples', '3')
        self.assertEqual(ActivityFlag.objects.count(), 0)

    def test_rerun_updates_instead_of_duplicating_and_keeps_review(self):
        doctor = make_doctor()
        admin = make_admin()
        flagged = Detection('DOCTOR', 10, flags=[{
            'user_id': doctor.user.id, 'features': {'distinct_patients': 40},
            'reasons': [{'feature': 'distinct_patients', 'value': 40, 'median': 6.0, 'z': 12.0, 'text': 'x'}],
        }])
        with mock.patch('apps.audit.management.commands.flag_activity_anomalies.detect', return_value=flagged):
            run('--role', 'DOCTOR')
            ActivityFlag.objects.update(status='REVIEWED', reviewed_by=admin, note='checked')
            out = run('--role', 'DOCTOR')
        self.assertIn('0 new flags, 1 updated', out)
        # The admin is told once, when the flag is created, not on every rerun.
        self.assertEqual(Notification.objects.filter(receiver=admin, title__startswith='Unusual activity').count(), 1)
        flag = ActivityFlag.objects.get()
        self.assertEqual(flag.status, 'REVIEWED')
        self.assertEqual(flag.note, 'checked')
        doctor.user.refresh_from_db()
        self.assertTrue(doctor.user.is_active)                 # flags never change the account

    def test_bad_arguments(self):
        with self.assertRaises(Exception):
            run('--eps', '0')


@override_settings(SECURE_SSL_REDIRECT=False)
class ActivityFlagApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin()
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.flag = make_flag(self.doctor.user)

    def test_non_admins_are_rejected(self):
        for user in (self.doctor.user, self.patient.user):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(FLAGS_URL).status_code, 403)
            self.assertEqual(self.client.patch(f'{FLAGS_URL}{self.flag.id}/', {'status': 'DISMISSED'},
                                               format='json').status_code, 403)
            self.assertEqual(self.client.get(SETTINGS_URL).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(FLAGS_URL).status_code, 401)
        self.flag.refresh_from_db()
        self.assertEqual(self.flag.status, 'NEW')

    def test_admin_lists_and_reviews_with_audit_entry(self):
        self.client.force_authenticate(self.admin)
        rows = self.client.get(FLAGS_URL).json()['results']
        self.assertEqual(rows[0]['username'], self.doctor.user.username)
        self.assertEqual(rows[0]['reasons'][0], {
            'metric': 'distinct_patients',
            'text': 'Opened 40 patient records. Most doctors opened 6.',
            'detail': 'distinct_patients = 40, role median 6, robust z +12.0',
        })
        self.assertEqual(rows[0]['severity'], 'HIGH')

        res = self.client.patch(f'{FLAGS_URL}{self.flag.id}/',
                                {'status': 'REVIEWED', 'note': 'Covering a colleague', 'eps': 9}, format='json')
        self.assertEqual(res.status_code, 200)
        self.flag.refresh_from_db()
        self.assertEqual((self.flag.status, self.flag.note, self.flag.reviewed_by), ('REVIEWED', 'Covering a colleague', self.admin))
        self.assertEqual(self.flag.eps, 1.0)                   # detection fields are read-only
        log = AuditLog.objects.get(action='REVIEW_ACTIVITY_FLAG')
        self.assertEqual(log.user, self.admin)
        self.assertIn('Covering a colleague', log.description)

    def test_invalid_status_and_no_delete(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(f'{FLAGS_URL}{self.flag.id}/', {'status': 'LOCKED'},
                                           format='json').status_code, 400)
        self.assertEqual(self.client.delete(f'{FLAGS_URL}{self.flag.id}/').status_code, 405)

    def test_settings_defaults_validation_and_update(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(SETTINGS_URL).json()['dbscan_eps'], 1.0)
        for bad in ({'activity_window_days': 0}, {'dbscan_eps': 0}, {'dbscan_min_samples': 1}):
            body = {'activity_window_days': 30, 'dbscan_eps': 1.0, 'dbscan_min_samples': 5, **bad}
            self.assertEqual(self.client.put(SETTINGS_URL, body, format='json').status_code, 400, bad)
        res = self.client.put(SETTINGS_URL, {'activity_window_days': 14, 'dbscan_eps': 1.5, 'dbscan_min_samples': 4},
                              format='json')
        self.assertEqual(res.status_code, 200)
        conf = ActivitySettings.load()
        self.assertEqual((conf.activity_window_days, conf.dbscan_eps, conf.dbscan_min_samples), (14, 1.5, 4))
        self.assertTrue(AuditLog.objects.filter(action='UPDATE_ACTIVITY_SETTINGS').exists())

    def test_settings_model_validation(self):
        with self.assertRaises(ValidationError):
            ActivitySettings(dbscan_eps=-1).save()


@override_settings(SECURE_SSL_REDIRECT=False)
class PatientReferenceTests(TestCase):
    def test_viewing_a_patient_records_the_patient(self):
        admin = make_admin()
        patient = make_patient()
        client = APIClient()
        client.force_authenticate(admin)
        self.assertEqual(client.get(f'/api/v1/patients/{patient.pk}/').status_code, 200)
        log = AuditLog.objects.get(action='VIEW_PATIENT')
        self.assertEqual((log.user, log.patient), (admin, patient))

    def test_failed_login_is_logged_without_changing_the_response(self):
        patient = make_patient()
        client = APIClient()
        res = client.post('/api/v1/auth/login/', {'username': patient.user.username, 'password': 'wrong'}, format='json')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(AuditLog.objects.get(action='LOGIN_FAILED').user, patient.user)
        client.post('/api/v1/auth/login/', {'username': 'nobody', 'password': 'wrong'}, format='json')
        self.assertEqual(AuditLog.objects.filter(action='LOGIN_FAILED').count(), 1)


ANALYSIS_URL = '/api/v1/activity-analysis/'


@override_settings(SECURE_SSL_REDIRECT=False)
class ActivityAnalysisApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin()

    def test_non_admins_are_rejected(self):
        doctor = make_doctor()
        self.client.force_authenticate(doctor.user)
        self.assertEqual(self.client.get(ANALYSIS_URL).status_code, 403)
        self.assertEqual(self.client.post(ANALYSIS_URL, {'role': 'DOCTOR'}, format='json').status_code, 403)

    def test_demo_preview_shows_steps_and_saves_nothing(self):
        self.client.force_authenticate(self.admin)
        res = self.client.get(ANALYSIS_URL, {'role': 'DOCTOR', 'demo': 'true', 'eps': 2, 'min_samples': 5})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['demo'])
        self.assertEqual(data['n_users'], len(data['users']))
        self.assertGreater(data['counts']['noise'], 0)
        self.assertTrue(data['users'][0]['username'].startswith('demo-user-'))
        self.assertIn('scaled', data['users'][0])
        self.assertEqual(ActivityFlag.objects.count(), 0)
        self.assertEqual(self.client.post(ANALYSIS_URL, {'demo': True}, format='json').status_code, 400)

    def test_real_preview_with_too_few_users_is_skipped(self):
        self.client.force_authenticate(self.admin)
        data = self.client.get(ANALYSIS_URL, {'role': 'ADMIN'}).json()
        self.assertTrue(data['skipped'])
        self.assertEqual(data['eps'], ActivitySettings.load().dbscan_eps)
        res = self.client.post(ANALYSIS_URL, {'role': 'ADMIN'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_bad_parameters(self):
        self.client.force_authenticate(self.admin)
        for bad in ({'eps': 0}, {'min_samples': 1}, {'days': 0}, {'role': 'ROOT'}):
            self.assertEqual(self.client.get(ANALYSIS_URL, bad).status_code, 400, bad)

    def test_save_flags_is_audited(self):
        doctor = make_doctor()
        flagged = Detection('DOCTOR', 12, flags=[{'user_id': doctor.user.id, 'features': {}, 'reasons': []}])
        self.client.force_authenticate(self.admin)
        with mock.patch('apps.audit.views.detect', return_value=flagged):
            res = self.client.post(ANALYSIS_URL, {'role': 'DOCTOR', 'eps': 2}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['created'], 1)
        self.assertEqual(ActivityFlag.objects.get().eps, 2.0)
        self.assertTrue(AuditLog.objects.filter(action='RUN_ACTIVITY_ANALYSIS', user=self.admin).exists())

    def test_auto_uses_the_suggested_parameters(self):
        self.client.force_authenticate(self.admin)
        data = self.client.get(ANALYSIS_URL, {'role': 'DOCTOR', 'demo': 'true', 'auto': 'true'}).json()
        self.assertTrue(data['auto'])
        self.assertFalse(data['skipped'])
        self.assertEqual((data['eps'], data['min_samples']), (data['suggested']['eps'], data['suggested']['min_samples']))
        # Too few users: still skipped, and the minimum is the smallest group DBSCAN runs on.
        few = self.client.get(ANALYSIS_URL, {'role': 'ADMIN', 'auto': 'true'}).json()
        self.assertTrue(few['skipped'])
        self.assertEqual(few['min_users'], 6)

    def test_save_flags_for_chosen_users_only(self):
        a, b = make_doctor(), make_doctor('doc2', license_number='NMC-1002')
        flagged = Detection('DOCTOR', 12, flags=[{'user_id': u.user.id, 'features': {}, 'reasons': []} for u in (a, b)])
        self.client.force_authenticate(self.admin)
        with mock.patch('apps.audit.views.detect', return_value=flagged):
            res = self.client.post(ANALYSIS_URL, {'role': 'DOCTOR', 'eps': 2, 'min_samples': 3,
                                                  'user_ids': [b.user.id]}, format='json')
        self.assertEqual(res.json()['flagged'], 1)
        self.assertEqual(ActivityFlag.objects.get().user, b.user)

    def test_sending_again_reopens_a_dismissed_flag(self):
        doctor = make_doctor()
        flagged = Detection('DOCTOR', 12, flags=[{'user_id': doctor.user.id, 'features': {}, 'reasons': []}])
        self.client.force_authenticate(self.admin)
        send = lambda: self.client.post(ANALYSIS_URL, {'role': 'DOCTOR', 'eps': 2, 'user_ids': [doctor.user.id]},
                                        format='json')
        with mock.patch('apps.audit.views.detect', return_value=flagged):
            send()
            ActivityFlag.objects.update(status=ActivityFlag.Status.DISMISSED, reviewed_by=self.admin)
            res = send()
        self.assertEqual(res.json()['updated'], 1)
        flag = ActivityFlag.objects.get()
        self.assertEqual((flag.status, flag.reviewed_by), (ActivityFlag.Status.NEW, None))
        self.assertEqual(self.client.get(FLAGS_URL, {'status': 'NEW'}).json()['count'], 1)
        self.assertEqual(Notification.objects.filter(receiver=self.admin, title__startswith='Unusual').count(), 2)

    def test_suspicious_alerts_are_shown_and_can_be_sent_even_when_skipped(self):
        patient = make_patient().user
        for _ in range(3):
            AuditLog.objects.create(user=patient, action='LOGIN_FAILED', description='Failed login.')
        alert = SuspiciousAlert.objects.create(user=patient, day=timezone.localdate(), reason='failed logins in 10 min = 6')
        SuspiciousAlert.objects.create(user=make_doctor().user, day=timezone.localdate(), reason='other role')
        self.client.force_authenticate(self.admin)
        data = self.client.get(ANALYSIS_URL, {'role': 'PATIENT', 'days': 7, 'auto': 'true'}).json()
        self.assertTrue(data['skipped'])                               # one patient: DBSCAN cannot run
        self.assertEqual([a['id'] for a in data['suspicious_alerts']], [alert.id])
        res = self.client.post(ANALYSIS_URL, {'role': 'PATIENT', 'days': 7, 'auto': True, 'user_ids': [patient.id]},
                               format='json')
        self.assertEqual((res.status_code, res.json()['flagged']), (200, 1))
        flag = ActivityFlag.objects.get()
        self.assertEqual((flag.user, flag.features['failed_logins']), (patient, 3))
        # Other users without an alert still cannot be sent while DBSCAN is skipped.
        other = make_patient('pat2', phone='9800000003').user
        res = self.client.post(ANALYSIS_URL, {'role': 'PATIENT', 'days': 7, 'user_ids': [other.id]}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_window_days_limits_the_events(self):
        doctor = make_doctor()
        log = AuditLog.objects.create(user=doctor.user, action='VIEW_PATIENT', description='old view')
        AuditLog.objects.filter(pk=log.pk).update(timestamp=timezone.now() - timedelta(days=10))
        self.client.force_authenticate(self.admin)
        recent = self.client.get(ANALYSIS_URL, {'role': 'DOCTOR', 'days': 5}).json()
        older = self.client.get(ANALYSIS_URL, {'role': 'DOCTOR', 'days': 30}).json()
        self.assertEqual((recent['days'], recent['n_users']), (5, 0))
        self.assertEqual((older['days'], older['n_users']), (30, 1))


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False)
class SeedActivityTests(TestCase):
    def test_seeded_doctors_cluster_with_three_outliers_and_reset_removes_them(self):
        admin = make_admin()
        real = make_doctor()
        call_command('seed_activity', stdout=StringIO())
        self.assertEqual(User.objects.filter(username__startswith='seed_act_doc').count(), 15)
        self.assertTrue(SuspiciousAlert.objects.filter(user__username='seed_act_doc13').exists())  # failed-login burst
        with self.assertRaises(Exception):
            call_command('seed_activity', stdout=StringIO())        # already seeded

        client = APIClient()
        client.force_authenticate(admin)
        suggested = client.get(ANALYSIS_URL, {'role': 'DOCTOR', 'days': 30}).json()['suggested']
        params = {'role': 'DOCTOR', 'days': 30, **suggested}
        data = client.get(ANALYSIS_URL, params).json()
        noise = {u['username'] for u in data['users'] if u['kind'] == 'noise'}
        self.assertEqual(noise, {'seed_act_doc13', 'seed_act_doc14', 'seed_act_doc15'})
        self.assertEqual(data['n_clusters'], 1)
        self.assertEqual(client.post(ANALYSIS_URL, params, format='json').json()['created'], 3)
        self.assertEqual(Notification.objects.filter(receiver=admin, title__contains='seed_act_').count(), 4)

        call_command('seed_activity', '--reset', stdout=StringIO())
        self.assertFalse(User.objects.filter(username__startswith='seed_act_').exists())
        self.assertFalse(AuditLog.objects.filter(description__startswith='[SEED-ACTIVITY]').exists())
        self.assertFalse(Patient.objects.filter(patient_id__startswith='PAT-SEED').exists())
        self.assertFalse(AccessRequest.objects.filter(reason__startswith='[SEED-ACTIVITY]').exists())
        self.assertFalse(ActivityFlag.objects.exists())
        self.assertFalse(Notification.objects.filter(title__contains='seed_act_').exists())
        self.assertTrue(User.objects.filter(pk=real.user.pk).exists())     # real accounts untouched

    @override_settings(DEBUG=False)
    def test_refuses_without_debug(self):
        with self.assertRaises(Exception):
            call_command('seed_activity', stdout=StringIO())
