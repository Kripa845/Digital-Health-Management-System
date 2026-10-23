"""seed_demo must never put the public demo passwords on a live database or replace its real admin."""
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from apps.users.models import User

REMOTE = {'HOST': 'ep-demo-123.ap-southeast-1.aws.neon.tech'}
OWN = {'SEED_ADMIN_PASSWORD': 'Own-Admin-2026', 'SEED_DOCTOR_PASSWORD': 'Own-Doctor-2026',
       'SEED_PATIENT_PASSWORD': 'Own-Patient-2026'}


def seed():
    call_command('seed_demo', stdout=StringIO())


class SeedDemoTests(TestCase):
    def setUp(self):
        # migrate may have created an admin from DJANGO_ADMIN_* in .env; start without one.
        User.objects.filter(username='admin').delete()

    def test_local_database_uses_demo_passwords(self):
        seed()
        self.assertTrue(User.objects.get(username='admin').check_password('admin12345'))
        self.assertTrue(User.objects.get(username='dr.sharma').check_password('doctor12345'))
        self.assertTrue(User.objects.get(username='hari.tamang').check_password('patient12345'))

    def test_remote_database_refuses_public_passwords(self):
        with patch.dict(connection.settings_dict, REMOTE), self.assertRaisesMessage(CommandError, 'SEED_DOCTOR_PASSWORD'):
            seed()
        self.assertFalse(User.objects.filter(username='dr.sharma').exists())

    def test_remote_database_with_own_passwords(self):
        with patch.dict(connection.settings_dict, REMOTE), patch.dict('os.environ', OWN):
            seed()
        self.assertTrue(User.objects.get(username='admin').check_password('Own-Admin-2026'))
        self.assertTrue(User.objects.get(username='dr.sharma').check_password('Own-Doctor-2026'))
        self.assertTrue(User.objects.get(username='hari.tamang').check_password('Own-Patient-2026'))

    def test_existing_admin_is_kept_with_its_password(self):
        real = User.objects.create_user(username='admin', password='Real-Admin-Pass-1', role=User.Role.ADMIN,
                                        is_staff=True, is_superuser=True)
        seed()
        seed()   # a rerun replaces the demo doctors/patients but still keeps the admin
        admin = User.objects.get(username='admin')
        self.assertEqual(admin.pk, real.pk)
        self.assertTrue(admin.check_password('Real-Admin-Pass-1'))
        self.assertEqual(User.objects.filter(username='dr.sharma').count(), 1)

    def test_existing_admin_needs_no_admin_password_on_remote(self):
        User.objects.create_user(username='admin', password='Real-Admin-Pass-1', role=User.Role.ADMIN)
        own = {k: v for k, v in OWN.items() if k != 'SEED_ADMIN_PASSWORD'}
        with patch.dict(connection.settings_dict, REMOTE), patch.dict('os.environ', own):
            seed()
        self.assertTrue(User.objects.get(username='admin').check_password('Real-Admin-Pass-1'))

    def test_non_admin_named_admin_is_not_touched(self):
        User.objects.create_user(username='admin', password='x-Pass-12345', role=User.Role.PATIENT)
        with self.assertRaisesMessage(CommandError, 'not an admin'):
            seed()
