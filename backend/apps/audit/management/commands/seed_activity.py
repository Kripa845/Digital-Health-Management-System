"""Seeded test doctors with realistic activity, for the Activity analysis page (DBSCAN per role).

    python manage.py seed_activity              # 15 test doctors, 30 days of activity up to yesterday
    python manage.py seed_activity --days 14    # a shorter history
    python manage.py seed_activity --reset      # remove every seeded row, nothing else

Unlike seed_demo_audit this is meant for the normal development database, next
to real accounts, so the real-data path of the page has enough users to cluster.
It refuses to run when DEBUG is off unless --force is given.

12 doctors share one ordinary workload (daytime work on their own patient
panel, rare night-time or failed logins, a few access requests); 3 stand out:

    seed_act_doc13  night owl: most actions 22:00-04:00, failed logins, and one
                    burst of 8 failed logins yesterday (raises a SuspiciousAlert)
    seed_act_doc14  snooper: opens records of many different patients
    seed_act_doc15  denied: many access requests, most of them declined

Everything it creates is marked: usernames start with "seed_act_", patient IDs
with "PAT-SEED", audit descriptions and access-request reasons with
"[SEED-ACTIVITY]", and IP addresses come from 198.51.100.0/24. Seeded doctors
have unusable passwords and an Inactive doctor profile, so they cannot log in
and are not offered to patients. --reset deletes exactly those rows, plus the
admin notifications that name a seeded user.
"""
import random
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.brute_force import check_failed_logins
from apps.audit.models import AuditLog
from apps.doctors.models import AccessRequest, Doctor
from apps.notifications.models import Notification
from apps.patients.models import Patient
from apps.users.models import User

PREFIX = 'seed_act_'
PATIENT_PREFIX = 'PAT-SEED'
TAG = '[SEED-ACTIVITY]'
N_NORMAL = 12
N_PATIENTS = 120
PANEL_SIZE = 20                  # patients a normal doctor sees
SUSPICIOUS = {13: 'night_owl', 14: 'snooper', 15: 'denied'}
BURST_FAILED_LOGINS = 8
SEED = 2026


def ip(n: int) -> str:
    return f'198.51.100.{10 + n}'


class Command(BaseCommand):
    help = 'Seed 15 marked test doctors (12 normal, 3 suspicious) with audit activity for DBSCAN.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30, help='Days of history ending yesterday (default 30).')
        parser.add_argument('--reset', action='store_true', help='Remove every seeded row and stop.')
        parser.add_argument('--force', action='store_true', help='Run even when DEBUG is off.')

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts['force']:
            raise CommandError('DEBUG is off; this looks like production. Pass --force if you are sure.')
        if opts['days'] < 1:
            raise CommandError('--days must be at least 1.')
        with transaction.atomic():
            if opts['reset']:
                self.reset()
                return
            if User.objects.filter(username__startswith=PREFIX).exists():
                raise CommandError('Seeded doctors already exist. Run with --reset first to start again.')
            self.rng = random.Random(SEED)
            self.today = timezone.localdate()
            self.seed(opts['days'])

    def reset(self):
        logs = AuditLog.objects.filter(
            Q(user__username__startswith=PREFIX) | Q(patient__patient_id__startswith=PATIENT_PREFIX))
        n_logs, _ = logs.delete()             # a queryset delete never calls AuditLog.delete(); seeded rows only
        n_notes, _ = Notification.objects.filter(title__contains=PREFIX).delete()
        # Cascades to doctor/patient profiles, access requests, activity flags and suspicious alerts.
        n_users, _ = User.objects.filter(username__startswith=PREFIX).delete()
        self.stdout.write(self.style.SUCCESS(
            f'Removed {n_logs} seeded audit entries, {n_notes} admin notifications and {n_users} seeded objects.'))

    # ── accounts ──────────────────────────────────────────────────────────
    def seed(self, days):
        unusable = make_password(None)
        n_doctors = N_NORMAL + len(SUSPICIOUS)
        User.objects.bulk_create([
            User(username=f'{PREFIX}doc{n:02d}', role=User.Role.DOCTOR, password=unusable,
                 first_name='Seed', last_name=f'Doctor {n:02d}')
            for n in range(1, n_doctors + 1)
        ] + [
            User(username=f'{PREFIX}pat{n:03d}', role=User.Role.PATIENT, password=unusable,
                 first_name='Seed', last_name=f'Patient {n:03d}')
            for n in range(1, N_PATIENTS + 1)
        ])
        doctor_users = list(User.objects.filter(username__startswith=f'{PREFIX}doc').order_by('username'))
        for n, u in enumerate(doctor_users, start=1):     # save() fills doctor_id and uuid_token
            Doctor.objects.create(
                user=u, license_number=f'SEED-ACT-{n:02d}', department='General Medicine',
                specialization='General Practice', dob='1985-01-01', gender='Other', phone='9800000000',
                email=f'{u.username}@example.invalid', status='Inactive')
        patient_users = User.objects.filter(username__startswith=f'{PREFIX}pat').order_by('username')
        Patient.objects.bulk_create([
            Patient(user=u, patient_id=f'{PATIENT_PREFIX}{n:04d}', first_name='Seed', last_name=f'Patient {n:03d}',
                    dob='1990-01-01', gender='Other', blood_group='O+', phone='9800000000',
                    emergency_contact='9800000000', address=f'{TAG} synthetic test data', height=170, weight=70)
            for n, u in enumerate(patient_users, start=1)
        ])
        self.patients = list(Patient.objects.filter(patient_id__startswith=PATIENT_PREFIX).order_by('patient_id'))

        logs, requests = [], []
        for n, user in enumerate(doctor_users, start=1):
            self.doctor_activity(n, user, SUSPICIOUS.get(n, 'normal'), days, logs, requests)
        self.insert_logs(logs)
        self.insert_requests(requests)

        night_owl = doctor_users[12]
        burst_end = self.burst(night_owl)
        alert = check_failed_logins(night_owl, now=burst_end)   # the same rule a real login failure runs

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {n_doctors} test doctors ({N_NORMAL} normal, {len(SUSPICIOUS)} suspicious), '
            f'{N_PATIENTS} test patients, {len(logs) + BURST_FAILED_LOGINS} audit entries and '
            f'{len(requests)} access requests over the {days} days before {self.today}.'))
        for n, kind in SUSPICIOUS.items():
            self.stdout.write(f'  {PREFIX}doc{n:02d}: {kind}')
        if alert:
            self.stdout.write(f'  Failed-login burst raised suspicious alert {alert.id}: {alert.reason}')
        self.stdout.write('Remove everything later with: python manage.py seed_activity --reset')

    # ── activity ──────────────────────────────────────────────────────────
    def doctor_activity(self, n, user, kind, days, logs, requests):
        rng = self.rng
        level = rng.lognormvariate(0, 0.15)                 # this doctor's workload, similar for everyone
        panel = rng.sample(self.patients, PANEL_SIZE)
        profile = user.doctor_profile
        for back in range(days, 0, -1):
            day = self.today - timedelta(days=back)
            if rng.random() > 0.7:                          # about 5 working days a week
                continue
            night = kind == 'night_owl' and rng.random() < 0.75

            if rng.random() < (0.5 if kind == 'night_owl' else 0.04):
                logs.append(self.entry(user, 'LOGIN_FAILED', f'Failed login attempt for {user.username}.',
                                       self.at(day, 21 if night else 7, 22 if night else 8), n))
            logs.append(self.entry(user, 'LOGIN', f'User {user.username} logged in.',
                                   self.at(day, 22 if night else 8, 23 if night else 9), n))
            pool = self.patients if kind == 'snooper' else panel
            n_actions = rng.randint(40, 60) if kind == 'snooper' else max(1, round(rng.randint(6, 12) * level))
            for _ in range(n_actions):
                patient = rng.choice(pool)
                action = 'VIEW_PATIENT' if rng.random() < 0.8 else 'SCAN_QR'
                verb = 'Viewed patient record' if action == 'VIEW_PATIENT' else 'Scanned patient'
                when = self.at(day, 22, 28) if night else self.at(day, 9, 18)   # 22:00 to 04:00 the next morning
                logs.append(self.entry(user, action, f'{verb} {patient.patient_id}.', when, n, patient))
            if kind == 'normal' and rng.random() < 0.08:    # an occasional late check
                patient = rng.choice(panel)
                logs.append(self.entry(user, 'VIEW_PATIENT', f'Viewed patient record {patient.patient_id}.',
                                       self.at(day, 22, 23), n, patient))

            n_requests = rng.randint(2, 4) if kind == 'denied' else int(rng.random() < 0.15)
            for _ in range(n_requests):
                declined = rng.random() < (0.8 if kind == 'denied' else 0.1)
                requests.append((AccessRequest(
                    doctor=profile, patient=rng.choice(self.patients), status='DECLINED' if declined else 'APPROVED',
                    reason=f'{TAG} Needs the record for a consultation.'), self.at(day, 9, 17)))

    def burst(self, user):
        """BURST_FAILED_LOGINS failed logins 20 s apart, yesterday at 23:30; returns the moment after the last."""
        n = int(user.username[-2:])
        start = timezone.make_aware(datetime.combine(self.today - timedelta(days=1), time(23, 30)))
        times = [start + timedelta(seconds=20 * i) for i in range(BURST_FAILED_LOGINS)]
        self.insert_logs([self.entry(user, 'LOGIN_FAILED', f'Failed login attempt for {user.username}.', t, n)
                          for t in times])
        return times[-1] + timedelta(seconds=1)

    # ── helpers ───────────────────────────────────────────────────────────
    def at(self, day, first_hour, last_hour):
        """A random local time between first_hour:00 and last_hour:00 counted from `day`'s midnight."""
        start = timezone.make_aware(datetime.combine(day, time.min)) + timedelta(hours=first_hour)
        return start + timedelta(seconds=self.rng.randrange((last_hour - first_hour) * 3600))

    @staticmethod
    def entry(user, action, description, when, n, patient=None):
        return (AuditLog(user=user, action=action, description=f'{TAG} {description}', ip_address=ip(n),
                         patient=patient), when)

    @staticmethod
    def insert_logs(rows):
        """bulk_create stamps every row with now (auto_now_add), so the seeded times are set afterwards."""
        logs = AuditLog.objects.bulk_create([log for log, _ in rows], batch_size=1000)
        for log, (_, when) in zip(logs, rows):
            log.timestamp = when
        AuditLog.objects.bulk_update(logs, ['timestamp'], batch_size=500)

    @staticmethod
    def insert_requests(rows):
        objs = AccessRequest.objects.bulk_create([r for r, _ in rows])
        for obj, (_, when) in zip(objs, rows):
            obj.created_at = when
            obj.resolved_at = when + timedelta(hours=2)
        AccessRequest.objects.bulk_update(objs, ['created_at', 'resolved_at'])
