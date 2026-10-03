
import datetime as dt

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.patients.models import Patient
from apps.doctors.models import AccessRequest, Doctor, DoctorAssignment, Prescription
from apps.appointments.models import Appointment
from apps.documents.models import Document
from apps.notifications.models import Notification
from apps.recommendations.models import RecommendationHistory

User = get_user_model()

ADMIN = {
    'username': 'admin',
    'password': 'admin12345',
    'email': 'admin@merocare.local',
    'first_name': 'System',
    'last_name': 'Administrator',
}

DOCTOR_PASSWORD = 'doctor12345'
PATIENT_PASSWORD = 'patient12345'

# ---------------------------------------------------------------------------
# Doctors — username, name, department, specialization, gender, dob, phone
# ---------------------------------------------------------------------------
DOCTORS = [
    {
        'username': 'dr.sharma', 'first_name': 'Arjun', 'last_name': 'Sharma',
        'department': 'Cardiology', 'specialization': 'Interventional Cardiology',
        'gender': 'Male', 'dob': dt.date(1978, 4, 12), 'phone': '9801000001',
        'license_number': 'NMC-1001',
        'schedule': {'Monday': '09:00-17:00', 'Tuesday': '09:00-17:00', 'Wednesday': '09:00-13:00',
                     'Thursday': '09:00-17:00', 'Friday': '09:00-17:00', 'Saturday': 'closed', 'Sunday': 'closed'},
    },
    {
        'username': 'dr.gurung', 'first_name': 'Sita', 'last_name': 'Gurung',
        'department': 'Neurology', 'specialization': 'Clinical Neurology',
        'gender': 'Female', 'dob': dt.date(1982, 9, 3), 'phone': '9801000002',
        'license_number': 'NMC-1002',
        'schedule': {'Monday': '10:00-16:00', 'Tuesday': 'closed', 'Wednesday': '10:00-16:00',
                     'Thursday': '10:00-16:00', 'Friday': '10:00-16:00', 'Saturday': '10:00-13:00', 'Sunday': 'closed'},
    },
    {
        'username': 'dr.thapa', 'first_name': 'Bishnu', 'last_name': 'Thapa',
        'department': 'Pediatrics', 'specialization': 'General Pediatrics',
        'gender': 'Male', 'dob': dt.date(1985, 1, 22), 'phone': '9801000003',
        'license_number': 'NMC-1003',
        'schedule': {'Monday': '08:00-14:00', 'Tuesday': '08:00-14:00', 'Wednesday': '08:00-14:00',
                     'Thursday': '08:00-14:00', 'Friday': '08:00-14:00', 'Saturday': 'closed', 'Sunday': 'closed'},
    },
    {
        'username': 'dr.rai', 'first_name': 'Anita', 'last_name': 'Rai',
        'department': 'Dermatology', 'specialization': 'Cosmetic Dermatology',
        'gender': 'Female', 'dob': dt.date(1987, 6, 30), 'phone': '9801000004',
        'license_number': 'NMC-1004',
        'schedule': {},  # empty = always available
    },
    {
        'username': 'dr.karki', 'first_name': 'Ramesh', 'last_name': 'Karki',
        'department': 'Orthopedics', 'specialization': 'Joint Replacement',
        'gender': 'Male', 'dob': dt.date(1975, 11, 8), 'phone': '9801000005',
        'license_number': 'NMC-1005',
        'schedule': {'Monday': '09:00-17:00', 'Tuesday': '09:00-17:00', 'Wednesday': 'closed',
                     'Thursday': '09:00-17:00', 'Friday': '09:00-17:00', 'Saturday': '09:00-12:00', 'Sunday': 'closed'},
    },
    {
        'username': 'dr.shrestha', 'first_name': 'Gita', 'last_name': 'Shrestha',
        'department': 'General Medicine', 'specialization': 'Internal Medicine',
        'gender': 'Female', 'dob': dt.date(1980, 2, 17), 'phone': '9801000006',
        'license_number': 'NMC-1006',
        'schedule': {'Monday': '09:00-17:00', 'Tuesday': '09:00-17:00', 'Wednesday': '09:00-17:00',
                     'Thursday': '09:00-17:00', 'Friday': '09:00-17:00', 'Saturday': '09:00-14:00', 'Sunday': 'closed'},
    },
]

# ---------------------------------------------------------------------------
# Patients — full medical profiles with Nepali names
# ---------------------------------------------------------------------------
PATIENTS = [
    {
        'username': 'hari.tamang', 'first_name': 'Hari', 'middle_name': 'Bahadur', 'last_name': 'Tamang',
        'dob': dt.date(1990, 5, 14), 'gender': 'Male', 'blood_group': 'O+',
        'phone': '9811000001', 'emergency_contact': '9711000001', 'email': 'hari.tamang@example.com',
        'address': 'Baneshwor, Kathmandu', 'height': 172.5, 'weight': 70.0,
        'allergies': 'Penicillin', 'current_medication': 'Amlodipine 5mg once daily',
        'prescription': 'Continue BP medication; review in 3 months.',
        'pain_log': 'Occasional chest tightness on exertion.',
    },
    {
        'username': 'laxmi.poudel', 'first_name': 'Laxmi', 'middle_name': 'Devi', 'last_name': 'Poudel',
        'dob': dt.date(1985, 8, 2), 'gender': 'Female', 'blood_group': 'A+',
        'phone': '9811000002', 'emergency_contact': '9711000002', 'email': 'laxmi.poudel@example.com',
        'address': 'Lakeside, Pokhara', 'height': 158.0, 'weight': 55.5,
        'allergies': 'None known', 'current_medication': 'Levothyroxine 50mcg',
        'prescription': 'Thyroid function test every 6 months.',
        'pain_log': 'Frequent migraines, twice a week.',
    },
    {
        'username': 'krishna.adhikari', 'first_name': 'Krishna', 'middle_name': 'Prasad', 'last_name': 'Adhikari',
        'dob': dt.date(1962, 12, 20), 'gender': 'Male', 'blood_group': 'B+',
        'phone': '9811000003', 'emergency_contact': '9711000003', 'email': 'krishna.adhikari@example.com',
        'address': 'Biratnagar, Morang', 'height': 168.0, 'weight': 78.2,
        'allergies': 'Sulfa drugs', 'current_medication': 'Metformin 500mg twice daily, Atorvastatin 20mg',
        'prescription': 'Diabetic diet; HbA1c check quarterly.',
        'pain_log': 'Knee joint pain when climbing stairs.',
    },
    {
        'username': 'sunita.maharjan', 'first_name': 'Sunita', 'middle_name': None, 'last_name': 'Maharjan',
        'dob': dt.date(1998, 3, 9), 'gender': 'Female', 'blood_group': 'AB+',
        'phone': '9811000004', 'emergency_contact': '9711000004', 'email': 'sunita.maharjan@example.com',
        'address': 'Patan, Lalitpur', 'height': 162.0, 'weight': 58.0,
        'allergies': 'Dust, pollen', 'current_medication': 'Cetirizine as needed',
        'prescription': 'Antihistamine during allergy season.',
        'pain_log': 'Skin rash and itching on forearms.',
    },
    {
        'username': 'deepak.bhattarai', 'first_name': 'Deepak', 'middle_name': None, 'last_name': 'Bhattarai',
        'dob': dt.date(1972, 7, 25), 'gender': 'Male', 'blood_group': 'O-',
        'phone': '9811000005', 'emergency_contact': '9711000005', 'email': 'deepak.bhattarai@example.com',
        'address': 'Butwal, Rupandehi', 'height': 175.0, 'weight': 82.0,
        'allergies': 'None known', 'current_medication': 'Losartan 50mg once daily',
        'prescription': 'Monitor blood pressure at home.',
        'pain_log': 'Lower back pain after long drives.',
    },
    {
        'username': 'rita.lama', 'first_name': 'Rita', 'middle_name': None, 'last_name': 'Lama',
        'dob': dt.date(2015, 10, 5), 'gender': 'Female', 'blood_group': 'A-',
        'phone': '9811000006', 'emergency_contact': '9711000006', 'email': 'rita.lama@example.com',
        'address': 'Bhaktapur Durbar Square, Bhaktapur', 'height': 120.0, 'weight': 24.0,
        'allergies': 'Peanuts', 'current_medication': 'None',
        'prescription': 'Routine child vaccination up to date.',
        'pain_log': 'Recurrent fever and cough.',
    },
    {
        'username': 'prakash.koirala', 'first_name': 'Prakash', 'middle_name': None, 'last_name': 'Koirala',
        'dob': dt.date(1994, 1, 30), 'gender': 'Male', 'blood_group': 'B-',
        'phone': '9811000007', 'emergency_contact': '9711000007', 'email': 'prakash.koirala@example.com',
        'address': 'Dharan, Sunsari', 'height': 180.0, 'weight': 75.0,
        'allergies': 'None known', 'current_medication': 'None',
        'prescription': 'Physiotherapy for sprained ankle.',
        'pain_log': 'Ankle sprain from football.',
    },
    {
        'username': 'sarita.basnet', 'first_name': 'Sarita', 'middle_name': None, 'last_name': 'Basnet',
        'dob': dt.date(1959, 4, 18), 'gender': 'Female', 'blood_group': 'AB-',
        'phone': '9811000008', 'emergency_contact': '9711000008', 'email': 'sarita.basnet@example.com',
        'address': 'Hetauda, Makwanpur', 'height': 155.0, 'weight': 63.0,
        'allergies': 'Aspirin', 'current_medication': 'Amlodipine 10mg, Metformin 850mg',
        'prescription': 'Cardiology follow-up for palpitations.',
        'pain_log': 'Heart palpitations and breathlessness.',
    },
    {
        'username': 'nabin.shrestha', 'first_name': 'Nabin', 'middle_name': None, 'last_name': 'Shrestha',
        'dob': dt.date(2001, 11, 11), 'gender': 'Male', 'blood_group': 'O+',
        'phone': '9811000009', 'emergency_contact': '9711000009', 'email': 'nabin.shrestha@example.com',
        'address': 'Kirtipur, Kathmandu', 'height': 170.0, 'weight': 65.0,
        'allergies': 'None known', 'current_medication': 'None',
        'prescription': 'Advised rest and hydration.',
        'pain_log': 'Persistent headache and dizziness.',
    },
    {
        'username': 'manisha.khadka', 'first_name': 'Manisha', 'middle_name': None, 'last_name': 'Khadka',
        'dob': dt.date(1989, 6, 21), 'gender': 'Female', 'blood_group': 'A+',
        'phone': '9811000010', 'emergency_contact': '9711000010', 'email': 'manisha.khadka@example.com',
        'address': 'Itahari, Sunsari', 'height': 160.0, 'weight': 60.0,
        'allergies': 'Latex', 'current_medication': 'Iron supplements',
        'prescription': 'Dermatology review for eczema.',
        'pain_log': 'Eczema flare-ups on hands.',
    },
]


class Command(BaseCommand):
    help = 'Seed rich, realistic demo data (admin, doctors, patients, appointments, etc.).'

    @transaction.atomic
    def handle(self, *args, **options):
        self._wipe_previous()

        admin = self._create_admin()
        doctors = self._create_doctors()
        patients = self._create_patients()
        self._create_assignments(doctors, patients)
        self._create_appointments(doctors, patients)
        self._create_prescriptions(doctors, patients)
        self._create_documents(admin, patients)
        self._create_notifications(admin, doctors, patients)
        self._create_recommendations(patients)

        self._print_credentials(admin, doctors, patients)

    # -- teardown ----------------------------------------------------------
    def _wipe_previous(self):
        usernames = [ADMIN['username']] + [d['username'] for d in DOCTORS] + [p['username'] for p in PATIENTS]
        qs = User.objects.filter(username__in=usernames)
        count = qs.count()
        if count:
            qs.delete()  # cascades to profiles, assignments, appointments, docs, notifications
            self.stdout.write(self.style.WARNING(f'Removed {count} previously seeded demo user(s).'))

    # -- creators ----------------------------------------------------------
    def _create_admin(self):
        admin = User.objects.create_user(
            username=ADMIN['username'],
            email=ADMIN['email'],
            password=ADMIN['password'],
            first_name=ADMIN['first_name'],
            last_name=ADMIN['last_name'],
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
            must_change_password=False,
        )
        self.stdout.write(self.style.SUCCESS(f'Created admin: {admin.username}'))
        return admin

    def _create_doctors(self):
        created = []
        for d in DOCTORS:
            user = User.objects.create_user(
                username=d['username'],
                email=f"{d['username']}@merocare.local",
                password=DOCTOR_PASSWORD,
                first_name=d['first_name'],
                last_name=d['last_name'],
                role=User.Role.DOCTOR,
                must_change_password=False,
            )
            doctor = Doctor.objects.create(
                user=user,
                license_number=d['license_number'],
                department=d['department'],
                specialization=d['specialization'],
                dob=d['dob'],
                gender=d['gender'],
                phone=d['phone'],
                email=user.email,
                status='Active',
                availability_schedule=d['schedule'],
            )
            created.append(doctor)
        self.stdout.write(self.style.SUCCESS(f'Created {len(created)} doctors.'))
        return created

    def _create_patients(self):
        created = []
        for n, p in enumerate(PATIENTS, start=1):
            user = User.objects.create_user(
                username=p['username'],
                email=p['email'],
                password=PATIENT_PASSWORD,
                first_name=p['first_name'],
                last_name=p['last_name'],
                role=User.Role.PATIENT,
                must_change_password=False,
            )
            patient = Patient.objects.create(
                user=user,
                # Patient IDs are typed by the admin; demo IDs are fixed (hex, like printed cards).
                patient_id=f'PAT-0DE0{n:04d}',
                first_name=p['first_name'],
                middle_name=p['middle_name'],
                last_name=p['last_name'],
                dob=p['dob'],
                gender=p['gender'],
                blood_group=p['blood_group'],
                phone=p['phone'],
                emergency_contact=p['emergency_contact'],
                email=p['email'],
                address=p['address'],
                height=p['height'],
                weight=p['weight'],
                allergies=p['allergies'],
                current_medication=p['current_medication'],
                prescription=p['prescription'],
                pain_log=p['pain_log'],
                status='Active',
            )
            created.append(patient)
        self.stdout.write(self.style.SUCCESS(f'Created {len(created)} patients.'))
        return created

    def _create_assignments(self, doctors, patients):
        # (doctor index, patient index) -> Active assignment
        pairs = [
            (5, 0),  # Gita Shrestha (GenMed)  <- Hari Tamang
            (1, 1),  # Sita Gurung (Neuro)     <- Laxmi Poudel
            (5, 2),  # Gita Shrestha (GenMed)  <- Krishna Adhikari
            (3, 3),  # Anita Rai (Derm)        <- Sunita Maharjan
            (4, 4),  # Ramesh Karki (Ortho)    <- Deepak Bhattarai
            (2, 5),  # Bishnu Thapa (Peds)     <- Rita Lama
            (0, 7),  # Arjun Sharma (Cardio)   <- Sarita Basnet
            (3, 9),  # Anita Rai (Derm)        <- Manisha Khadka
        ]
        n = 0
        for di, pi in pairs:
            DoctorAssignment.objects.create(doctor=doctors[di], patient=patients[pi], status='Active')
            # Same as an admin assignment through the API: access counts as approved.
            AccessRequest.objects.create(
                doctor=doctors[di], patient=patients[pi], status='APPROVED',
                reason='Assigned by administrator', resolved_at=timezone.now(),
            )
            n += 1
        self.stdout.write(self.style.SUCCESS(f'Created {n} doctor-patient assignments.'))

    def _create_appointments(self, doctors, patients):
        today = timezone.localdate()
        specs = [
            # patient idx, doctor idx, days offset, time, status, reason
            (0, 5, 2, dt.time(10, 0), 'PENDING', 'Routine blood-pressure check.'),
            (1, 1, 3, dt.time(11, 30), 'ACCEPTED', 'Migraine follow-up.'),
            (2, 5, -5, dt.time(9, 0), 'COMPLETED', 'Diabetes review.'),
            (4, 4, 1, dt.time(14, 0), 'ACCEPTED', 'Lower back pain assessment.'),
            (7, 0, -2, dt.time(15, 30), 'CANCELLED', 'Palpitations consultation.'),
            (5, 2, 4, dt.time(8, 30), 'PENDING', 'Fever and cough in child.'),
            (9, 3, -8, dt.time(13, 0), 'DECLINED', 'Eczema consultation.'),
        ]
        n = 0
        for pi, di, offset, when, st, reason in specs:
            appt = Appointment.objects.create(
                patient=patients[pi],
                doctor=doctors[di],
                appointment_date=today + dt.timedelta(days=offset),
                appointment_time=when,
                status=st,
                reason=reason,
            )
            if st == 'ACCEPTED':
                appt.approved_by = doctors[di].user
                appt.save(update_fields=['approved_by'])
            elif st == 'COMPLETED':
                appt.approved_by = doctors[di].user
                appt.completed_at = timezone.now()
                appt.save(update_fields=['approved_by', 'completed_at'])
            elif st == 'CANCELLED':
                appt.cancelled_at = timezone.now()
                appt.save(update_fields=['cancelled_at'])
            n += 1
        self.stdout.write(self.style.SUCCESS(f'Created {n} appointments.'))

    def _create_prescriptions(self, doctors, patients):
        specs = [
            (2, 5, 'Type 2 Diabetes Mellitus', 'Metformin 500mg BD; Atorvastatin 20mg OD', 'Maintain diabetic diet and exercise.'),
            (1, 1, 'Chronic migraine', 'Sumatriptan 50mg PRN; Propranolol 40mg OD', 'Avoid known triggers; keep a headache diary.'),
            (4, 4, 'Lumbar muscle strain', 'Ibuprofen 400mg TDS x5 days', 'Physiotherapy referral; avoid heavy lifting.'),
        ]
        n = 0
        for pi, di, diagnosis, meds, notes in specs:
            Prescription.objects.create(
                patient=patients[pi],
                doctor=doctors[di].user,
                diagnosis=diagnosis,
                medications=meds,
                notes=notes,
            )
            n += 1
        self.stdout.write(self.style.SUCCESS(f'Created {n} prescriptions.'))

    def _create_documents(self, admin, patients):
        pdf_bytes = b'%PDF-1.4\n%demo Mero Care Card seed document\n'
        specs = [
            (2, 'MEDICAL', 'HbA1c Lab Report.pdf'),
            (7, 'MEDICAL', 'ECG Report.pdf'),
            (0, 'ADDITIONAL', 'Previous Prescription.pdf'),
        ]
        n = 0
        for pi, rtype, fname in specs:
            doc = Document(patient=patients[pi], report_type=rtype, uploaded_by=admin)
            doc.file.save(fname, ContentFile(pdf_bytes), save=False)
            doc.save()
            n += 1
        self.stdout.write(self.style.SUCCESS(f'Created {n} documents.'))

    def _create_notifications(self, admin, doctors, patients):
        Notification.objects.create(
            receiver=admin, role='ADMIN', title='Welcome to Mero Care Card',
            message='Demo data has been seeded. Explore the admin dashboard.',
        )
        Notification.objects.create(
            receiver=doctors[1].user, role='DOCTOR', title='New Appointment Request',
            message='A patient has requested a migraine follow-up appointment.',
        )
        Notification.objects.create(
            receiver=patients[0].user, role='PATIENT', title='Appointment Reminder',
            message='You have an upcoming blood-pressure check with Dr. Gita Shrestha.',
        )
        self.stdout.write(self.style.SUCCESS('Created 3 notifications.'))

    def _create_recommendations(self, patients):
        # Import lazily so data files load once.
        from apps.recommendations.views import build_recommendation

        specs = [
            (7, 'chest pain and palpitations with breathlessness', 8, 66, 'hypertension'),
            (1, 'severe headache and migraine with dizziness', 6, 40, ''),
            (5, 'child with high fever and continuous cough', 4, 9, ''),
        ]
        n = 0
        for pi, symptoms, pain, age, history in specs:
            result = build_recommendation(symptoms, pain, age, history)
            RecommendationHistory.objects.create(
                patient=patients[pi],
                symptoms=symptoms,
                pain_level=pain,
                age=age,
                medical_history=history,
                recommended_doctor=result['primary'],
                recommended_department=result['department'],
                score=result['score'],
                confidence=result['confidence'],
                reason=result['reason'],
            )
            n += 1
        self.stdout.write(self.style.SUCCESS(f'Created {n} recommendation-history rows.'))

    # -- report ------------------------------------------------------------
    def _print_credentials(self, admin, doctors, patients):
        line = '=' * 78
        self.stdout.write('\n' + line)
        self.stdout.write('  MERO CARE CARD - DEMO CREDENTIALS')
        self.stdout.write('  (all accounts: must_change_password=False)')
        self.stdout.write(line)
        header = f'  {"ROLE":<9} {"USERNAME":<20} {"PASSWORD":<15} {"NAME / DEPT":<28}'
        self.stdout.write(header)
        self.stdout.write('  ' + '-' * 74)

        self.stdout.write(f'  {"ADMIN":<9} {admin.username:<20} {ADMIN["password"]:<15} {"System Administrator":<28}')

        for d in doctors:
            name = f'Dr. {d.user.first_name} {d.user.last_name} - {d.department}'
            self.stdout.write(f'  {"DOCTOR":<9} {d.user.username:<20} {DOCTOR_PASSWORD:<15} {name:<28}')

        for p in patients:
            name = f'{p.first_name} {p.last_name} ({p.blood_group})'
            self.stdout.write(f'  {"PATIENT":<9} {p.user.username:<20} {PATIENT_PASSWORD:<15} {name:<28}')

        self.stdout.write(line)
        self.stdout.write(f'  Doctors: {len(doctors)}   Patients: {len(patients)}   '
                          f'Login endpoint: POST /api/v1/auth/login/')
        self.stdout.write(line + '\n')
