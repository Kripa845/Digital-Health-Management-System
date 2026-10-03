"""Create the fake patient the sample reports and the Playwright test use.

    python manage.py seed_e2e

Patient: Asha Gurung, ID PAT-0E2E0001, born 10 April 1992, blood group O+.
Login:   e2e.patient / the value of E2E_PATIENT_PASSWORD (default "Kathmandu-Lab-2026").
Admin:   e2e.admin   / the value of E2E_ADMIN_PASSWORD   (default "Kathmandu-Admin-2026").

Running it again resets that patient's lab data, so each test run starts clean.
Use it only on a development or test database.
"""
import os
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.lab_reports.models import LabReport
from apps.patients.models import Patient
from apps.users.models import User

PATIENT_ID = 'PAT-0E2E0001'


class Command(BaseCommand):
    help = 'Create (or reset) the fake patient used by the sample lab reports and e2e tests.'

    @transaction.atomic
    def handle(self, *args, **options):
        patient_password = os.environ.get('E2E_PATIENT_PASSWORD', 'Kathmandu-Lab-2026')
        admin_password = os.environ.get('E2E_ADMIN_PASSWORD', 'Kathmandu-Admin-2026')

        user, _ = User.objects.get_or_create(username='e2e.patient', defaults={'role': User.Role.PATIENT})
        user.role, user.first_name, user.last_name, user.email = User.Role.PATIENT, 'Asha', 'Gurung', 'asha.e2e@example.com'
        user.must_change_password, user.is_active = False, True
        user.set_password(patient_password)
        user.save()

        patient = Patient.objects.filter(patient_id=PATIENT_ID).first() or Patient(user=user, patient_id=PATIENT_ID)
        patient.user = user
        for field, value in dict(
            first_name='Asha', middle_name='', last_name='Gurung', dob=date(1992, 4, 10), gender='Female',
            blood_group='O+', phone='9801234500', emergency_contact='9801234501', email='asha.e2e@example.com',
            address='Lalitpur-3, Nepal', height=158, weight=54,
        ).items():
            setattr(patient, field, value)
        for field in ('hemoglobin', 'cholesterol_total', 'blood_sugar_random', 'blood_sugar_fasting'):
            setattr(patient, field, None)
        patient.save()
        for report in LabReport.objects.filter(patient=patient):
            report.delete()   # also removes stored files and value history

        admin, _ = User.objects.get_or_create(username='e2e.admin', defaults={'role': User.Role.ADMIN})
        admin.role, admin.first_name, admin.last_name = User.Role.ADMIN, 'Test', 'Admin'
        admin.must_change_password, admin.is_active = False, True
        admin.set_password(admin_password)
        admin.save()

        self.stdout.write(self.style.SUCCESS(f'e2e patient ready: e2e.patient ({PATIENT_ID}); admin: e2e.admin'))
