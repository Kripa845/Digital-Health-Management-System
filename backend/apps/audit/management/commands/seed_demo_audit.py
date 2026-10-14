"""Synthetic audit activity for demonstrating detect_suspicious. Never real patient data.

    python manage.py seed_demo_audit                         # 14 days of history + today, normal only
    python manage.py seed_demo_audit --attack brute_force    # 25 failed logins for one doctor today
    python manage.py seed_demo_audit --attack snooping       # 200+ different patients opened at 2 a.m.
    python manage.py seed_demo_audit --attack export         # 900 records read in one 45-minute session
    python manage.py seed_demo_audit --reset                 # remove every demo row, nothing else

Run it against a separate demo database (DATABASE_URL=sqlite:///demo.sqlite3).
Everything it creates is marked so it cannot be mistaken for real data:
usernames start with "demo_sa_", patient IDs with "PAT-DEMO", audit
descriptions with "[DEMO]", and IP addresses come from the documentation
ranges 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24. It refuses to run
on a database that holds any non-demo doctor or patient unless --force is given.

Audit entries are append-only through the model; the demo rows get their
past timestamps and are removed with queryset updates/deletes, which only
ever touch rows of demo users.
"""
import random
from datetime import datetime, time, timedelta

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.patients.models import Patient
from apps.users.models import User

PREFIX = 'demo_sa_'
PATIENT_PREFIX = 'PAT-DEMO'
ADMIN_USERNAME = f'{PREFIX}admin'
DEFAULT_ADMIN_PASSWORD = 'DemoAdmin#2026'
N_DOCTORS = 12
N_PATIENTS = 220
PANEL_SIZE = 15                  # patients each doctor normally sees
HISTORY_DAYS = 14
ATTACKERS = {'brute_force': 'doc03', 'snooping': 'doc07', 'export': 'doc11'}
ATTACKER_IP = '203.0.113.66'
SEED = 2026


def home_ip(n: int) -> str:
    return f'192.0.2.{10 + n}'


def ward_ip(n: int) -> str:
    return f'198.51.100.{10 + n}'


class Command(BaseCommand):
    help = 'Seed synthetic (demo-only) audit activity and optional attacks for detect_suspicious.'

    def add_arguments(self, parser):
        parser.add_argument('--attack', choices=sorted(ATTACKERS), help='Add one suspicious day for one doctor today.')
        parser.add_argument('--reset', action='store_true', help='Remove all demo users, patients, audit rows and alerts.')
        parser.add_argument('--admin-password', default=DEFAULT_ADMIN_PASSWORD,
                            help=f'Password for {ADMIN_USERNAME} (default {DEFAULT_ADMIN_PASSWORD}).')
        parser.add_argument('--force', action='store_true', help='Run even though the database has non-demo users.')

    def handle(self, *args, **opts):
        # Admin accounts (e.g. the one ensure_admin_user creates on migrate) are operators, not data.
        real = User.objects.exclude(username__startswith=PREFIX).exclude(role=User.Role.ADMIN)
        if not opts['force'] and real.exists():
            raise CommandError(
                'This database has doctors or patients that are not demo users. Use a separate demo database, e.g. '
                'DATABASE_URL=sqlite:///demo.sqlite3, or pass --force if you are sure.')
        self.rng = random.Random(SEED if not opts['attack'] else f"{SEED}-{opts['attack']}")
        self.today = timezone.localdate()
        with transaction.atomic():
            if opts['reset']:
                self.reset()
                return
            if not AuditLog.objects.filter(user__username__startswith=PREFIX).exists():
                self.seed_normal(opts['admin_password'])
            else:
                self.stdout.write('Normal demo activity is already there (use --reset to start again).')
            if opts['attack']:
                self.seed_attack(opts['attack'])

    def reset(self):
        demo_logs = AuditLog.objects.filter(
            Q(user__username__startswith=PREFIX) | Q(patient__patient_id__startswith=PATIENT_PREFIX))
        n_logs, _ = demo_logs.delete()        # a queryset delete never calls AuditLog.delete(); demo rows only
        n_users, _ = User.objects.filter(username__startswith=PREFIX).delete()   # cascades patients, alerts, notifications
        self.stdout.write(self.style.SUCCESS(f'Removed {n_logs} demo audit entries and {n_users} demo objects.'))

    # ── normal activity ───────────────────────────────────────────────────
    def seed_normal(self, admin_password):
        admin = User.objects.filter(username=ADMIN_USERNAME).first() or User.objects.create_user(
            ADMIN_USERNAME, password=admin_password, role=User.Role.ADMIN, is_staff=True, is_superuser=True,
            first_name='Demo', last_name='Admin')
        unusable = make_password(None)
        User.objects.bulk_create([
            User(username=f'{PREFIX}doc{n:02d}', role=User.Role.DOCTOR, password=unusable,
                 first_name='Demo', last_name=f'Doctor {n:02d}')
            for n in range(1, N_DOCTORS + 1)
        ] + [
            User(username=f'{PREFIX}pat{n:03d}', role=User.Role.PATIENT, password=unusable,
                 first_name='Demo', last_name=f'Patient {n:03d}')
            for n in range(1, N_PATIENTS + 1)
        ])
        patient_users = User.objects.filter(username__startswith=f'{PREFIX}pat').order_by('username')
        Patient.objects.bulk_create([
            Patient(user=u, patient_id=f'{PATIENT_PREFIX}{n:04d}', first_name='Demo', last_name=f'Patient {n:03d}',
                    dob='1990-01-01', gender='Other', blood_group='O+', phone='9800000000',
                    emergency_contact='9800000000', address='Synthetic demo data', height=170, weight=70)
            for n, u in enumerate(patient_users, start=1)
        ])
        self.patients = list(Patient.objects.filter(patient_id__startswith=PATIENT_PREFIX).order_by('patient_id'))

        rows = []
        for n, doctor in enumerate(self.doctors(), start=1):
            panel = self.rng.sample(self.patients, PANEL_SIZE)
            for back in range(HISTORY_DAYS, -1, -1):
                day = self.today - timedelta(days=back)
                ips = [home_ip(n)] + ([ward_ip(n)] if self.rng.random() < 0.15 else [])
                for _ in range(self.rng.randint(2, 3)):
                    rows.append(self.entry(doctor, 'LOGIN', f'User {doctor.username} logged in.',
                                           self.at(day, 8, 17), self.rng.choice(ips)))
                for _ in range(self.rng.randint(20, 40)):
                    patient = self.rng.choice(panel)
                    action = 'VIEW_PATIENT' if self.rng.random() < 0.8 else 'SCAN_QR'
                    verb = 'Viewed patient record' if action == 'VIEW_PATIENT' else 'Scanned patient'
                    rows.append(self.entry(doctor, action, f'{verb} {patient.patient_id}.',
                                           self.at(day, 9, 17), self.rng.choice(ips), patient))
        self.insert(rows)
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(rows)} normal audit entries: {N_DOCTORS} demo doctors, {HISTORY_DAYS} days of history '
            f'plus today ({self.today}), {N_PATIENTS} synthetic patients. Admin login: {ADMIN_USERNAME} / {admin_password}'))

    # ── attacks (today) ───────────────────────────────────────────────────
    def seed_attack(self, kind):
        username = f'{PREFIX}{ATTACKERS[kind]}'
        doctor = User.objects.get(username=username)
        n = int(username[-2:])
        patients = list(Patient.objects.filter(patient_id__startswith=PATIENT_PREFIX).order_by('patient_id'))
        rows = []
        if kind == 'brute_force':
            start = self.moment(11, 0)
            rows = [self.entry(doctor, 'LOGIN_FAILED', f'Failed login attempt for {username}.',
                               start + timedelta(seconds=20 * i), ATTACKER_IP) for i in range(25)]
            what = '25 failed logins from 203.0.113.66 at 11:00'
        elif kind == 'snooping':
            start = self.moment(2, 0)
            rows.append(self.entry(doctor, 'LOGIN', f'User {username} logged in.', start, home_ip(n)))
            for i, patient in enumerate(self.rng.sample(patients, 210), start=1):
                rows.append(self.entry(doctor, 'VIEW_PATIENT', f'Viewed patient record {patient.patient_id}.',
                                       start + timedelta(seconds=15 * i), home_ip(n), patient))
            what = '210 different patients opened between 02:00 and 03:00'
        else:
            start = self.moment(10, 0)
            rows.append(self.entry(doctor, 'LOGIN', f'User {username} logged in.', start, home_ip(n)))
            for i in range(900):
                patient = patients[i % len(patients)]
                rows.append(self.entry(doctor, 'VIEW_PATIENT', f'Viewed patient record {patient.patient_id}.',
                                       start + timedelta(seconds=3 * (i + 1)), home_ip(n), patient))
            what = '900 records read in one 45-minute session from 10:00'
        self.insert(rows)
        self.stdout.write(self.style.WARNING(f'Attack "{kind}" seeded for {username} today: {what}.'))

    # ── helpers ───────────────────────────────────────────────────────────
    def doctors(self):
        return User.objects.filter(username__startswith=f'{PREFIX}doc').order_by('username')

    def moment(self, hour, minute):
        return timezone.make_aware(datetime.combine(self.today, time(hour, minute)))

    def at(self, day, first_hour, last_hour):
        """A random local time on `day` between first_hour:00 and last_hour:00."""
        start = timezone.make_aware(datetime.combine(day, time(first_hour)))
        return start + timedelta(seconds=self.rng.randrange((last_hour - first_hour) * 3600))

    @staticmethod
    def entry(user, action, description, when, ip, patient=None):
        return (AuditLog(user=user, action=action, description=f'[DEMO] {description}', ip_address=ip,
                         patient=patient), when)

    @staticmethod
    def insert(rows):
        """bulk_create stamps every row with now (auto_now_add), so the demo times are set afterwards."""
        logs = AuditLog.objects.bulk_create([log for log, _ in rows], batch_size=1000)
        for log, (_, when) in zip(logs, rows):
            log.timestamp = when
        AuditLog.objects.bulk_update(logs, ['timestamp'], batch_size=500)
