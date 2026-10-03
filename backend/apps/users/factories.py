"""Small helpers for building test data. Used by the tests in each app."""
import uuid

from apps.doctors.models import AccessRequest, Doctor, DoctorAssignment
from apps.patients.models import Patient
from apps.users.models import User


def make_admin(username='admin1'):
    return User.objects.create_user(username, password='Str0ng-pass-123', role='ADMIN')


def new_patient_id():
    """A random ID in the format admins type, e.g. PAT-9C0E059C."""
    return f"PAT-{uuid.uuid4().hex[:8].upper()}"


def make_patient(username='pat1', phone='9800000001', emergency='9800000002', **extra):
    user = User.objects.create_user(username, password='Str0ng-pass-123', role='PATIENT')
    fields = dict(
        user=user, patient_id=new_patient_id(), first_name='Hari', last_name='Tamang', dob='1990-01-01', gender='Male',
        blood_group='O+', phone=phone, emergency_contact=emergency, email=f'{username}@example.com',
        address='Kathmandu', height=170, weight=70,
    )
    fields.update(extra)
    return Patient.objects.create(**fields)


def make_doctor(username='doc1', license_number='NMC-1001', department='Cardiology', **extra):
    user = User.objects.create_user(
        username, password='Str0ng-pass-123', role='DOCTOR', first_name='Arjun', last_name='Sharma',
    )
    fields = dict(
        user=user, license_number=license_number, department=department, specialization='General',
        dob='1980-01-01', gender='Male', phone='9811111111', email=f'{username}@example.com',
    )
    fields.update(extra)
    return Doctor.objects.create(**fields)


def grant_access(doctor, patient):
    """Active assignment plus an approved request: the doctor access rule."""
    DoctorAssignment.objects.create(doctor=doctor, patient=patient, status='Active')
    AccessRequest.objects.create(doctor=doctor, patient=patient, status='APPROVED')
