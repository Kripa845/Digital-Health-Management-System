"""Register 50 doctors across every department, the same way the admin "Add doctor" form does.

    python manage.py register_doctors                       # a generated password per doctor, printed once
    python manage.py register_doctors --password Pass1234   # the same password for all of them
    python manage.py register_doctors --remove              # delete exactly these 50 doctors again

Each doctor goes through DoctorSerializer, so names, NMC number, phone and email
are validated and normalised like a real registration, the username is
dr.<surname>, and the doctor must change the password at first login. A doctor
whose NMC number is already registered is skipped, so running it twice is safe.
Emails use the reserved example.com domain, so nothing can reach a real inbox.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditLog
from apps.doctors.models import WEEKDAY_NAMES, Doctor
from apps.doctors.serializers import DoctorSerializer
from apps.users.models import User

# Nepal works Sunday to Friday; Saturday is the weekly holiday. Shift: (hours, days closed).
SHIFTS = {
    'day': ('09:00-17:00', ['Saturday']),
    'morning': ('08:00-14:00', ['Saturday']),
    'late': ('11:00-19:00', ['Saturday', 'Wednesday']),
    'short': ('10:00-16:00', ['Saturday', 'Tuesday']),
    'emergency': ('08:00-20:00', []),                      # emergency cover every day
}

# first, last, gender, department, specialization, years of experience, NMC number, phone, shift
DOCTORS = [
    ('Prakash', 'Adhikari', 'Male', 'General Medicine', 'Internal Medicine', 18, 11204, '9841023456', 'day'),
    ('Sunita', 'Basnet', 'Female', 'General Medicine', 'Infectious Diseases', 9, 12871, '9851034567', 'morning'),
    ('Dipesh', 'Bhattarai', 'Male', 'General Medicine', 'Geriatric Medicine', 4, 15432, '9803045678', 'late'),
    ('Kamala', 'Dahal', 'Female', 'Pulmonology', 'Respiratory Medicine', 14, 10987, '9841156789', 'day'),
    ('Nabin', 'Ghimire', 'Male', 'Pulmonology', 'Tuberculosis and Chest Diseases', 7, 13654, '9860267890', 'short'),
    ('Rajendra', 'Koirala', 'Male', 'Cardiology', 'Interventional Cardiology', 22, 8765, '9851278901', 'day'),
    ('Sabina', 'Joshi', 'Female', 'Cardiology', 'Echocardiography', 8, 14320, '9813389012', 'morning'),
    ('Bikash', 'Khadka', 'Male', 'ENT', 'Otology', 11, 12098, '9841490123', 'day'),
    ('Pooja', 'Lama', 'Female', 'ENT', 'Rhinology and Sinus Surgery', 5, 16210, '9861501234', 'late'),
    ('Suresh', 'Maharjan', 'Male', 'Emergency Medicine', 'Trauma and Critical Care', 12, 11876, '9851612345', 'emergency'),
    ('Anjali', 'Neupane', 'Female', 'Emergency Medicine', 'Emergency Medicine', 6, 15098, '9808723456', 'emergency'),
    ('Hari', 'Pandey', 'Male', 'Neurology', 'Stroke Medicine', 16, 10543, '9841834567', 'day'),
    ('Manisha', 'Paudel', 'Female', 'Neurology', 'Epilepsy', 9, 13987, '9851945678', 'short'),
    ('Binod', 'Pokharel', 'Male', 'Gastroenterology', 'Hepatology', 13, 12456, '9802056789', 'day'),
    ('Rina', 'Pradhan', 'Female', 'Ophthalmology', 'Cataract and Refractive Surgery', 10, 13210, '9843167890', 'morning'),
    ('Deepak', 'Rana', 'Male', 'Oncology', 'Medical Oncology', 19, 9876, '9851278012', 'day'),
    ('Sarita', 'Regmi', 'Female', 'Nephrology', 'Dialysis and Transplant', 12, 12765, '9861389123', 'short'),
    ('Kiran', 'Sapkota', 'Male', 'Endocrinology', 'Diabetes and Thyroid', 8, 14567, '9841490234', 'late'),
    ('Laxmi', 'Subedi', 'Female', 'Family Medicine', 'General Practice', 6, 15876, '9806501345', 'day'),
    ('Rohan', 'Tamang', 'Male', 'Pediatrics', 'Neonatology', 7, 14098, '9851612456', 'morning'),
    ('Sushma', 'Tiwari', 'Female', 'Gynecology', 'Obstetrics', 15, 11543, '9841723567', 'day'),
    ('Asmita', 'Upreti', 'Female', 'Gynecology', 'Infertility', 4, 16543, '9862834678', 'late'),
    ('Mahesh', 'Yadav', 'Male', 'Orthopedics', 'Spine Surgery', 20, 9432, '9851945789', 'day'),
    ('Nirmala', 'Bajracharya', 'Female', 'Orthopedics', 'Sports Medicine', 5, 16098, '9843056890', 'short'),
    ('Sanjay', 'Acharya', 'Male', 'Psychiatry', 'Child and Adolescent Psychiatry', 11, 13045, '9841167901', 'late'),
    ('Pratima', 'Bhandari', 'Female', 'Dermatology', 'Pediatric Dermatology', 9, 14876, '9851278123', 'morning'),
    ('Gopal', 'Chaudhary', 'Male', 'Urology', 'Kidney Stone Surgery', 17, 10234, '9807389234', 'day'),
    ('Shristi', 'Dhakal', 'Female', 'Dentistry', 'Orthodontics', 3, 17012, '9861490345', 'short'),
    ('Pemba', 'Sherpa', 'Male', 'Radiology', 'Interventional Radiology', 10, 13567, '9841501456', 'day'),
    ('Ishwor', 'Giri', 'Male', 'Pathology', 'Histopathology', 14, 11987, '9851612567', 'morning'),
    # Second batch: one more for every department that had only one or two doctors.
    ('Bimala', 'Bista', 'Female', 'Gastroenterology', 'Endoscopy', 9, 18214, '9841723678', 'late'),
    ('Ramesh', 'Bohara', 'Male', 'Ophthalmology', 'Glaucoma', 15, 10876, '9851834789', 'day'),
    ('Sangita', 'Budhathoki', 'Female', 'Oncology', 'Radiation Oncology', 8, 15321, '9861945890', 'short'),
    ('Tek', 'Chhetri', 'Male', 'Nephrology', 'Clinical Nephrology', 21, 9123, '9803056901', 'morning'),
    ('Kabita', 'Devkota', 'Female', 'Endocrinology', 'Pediatric Endocrinology', 6, 16789, '9841167012', 'day'),
    ('Arjun', 'Gautam', 'Male', 'Family Medicine', 'Community Health', 12, 12543, '9851278234', 'late'),
    ('Srijana', 'Kafle', 'Female', 'Pulmonology', 'Sleep Medicine', 10, 14012, '9862389345', 'day'),
    ('Yubraj', 'Kandel', 'Male', 'Pulmonology', 'Interventional Pulmonology', 3, 17654, '9841490456', 'morning'),
    ('Mina', 'Khatri', 'Female', 'General Medicine', 'Internal Medicine', 13, 11654, '9805501567', 'short'),
    ('Dinesh', 'Lamichhane', 'Male', 'General Medicine', 'Tropical Medicine', 25, 8432, '9851612678', 'day'),
    ('Sarala', 'Mahat', 'Female', 'Psychiatry', 'Addiction Psychiatry', 7, 15654, '9861723789', 'day'),
    ('Bishal', 'Malla', 'Male', 'Urology', 'Andrology', 6, 16321, '9841834890', 'late'),
    ('Rojina', 'Nepal', 'Female', 'Dentistry', 'Oral and Maxillofacial Surgery', 9, 14654, '9851945901', 'morning'),
    ('Umesh', 'Ojha', 'Male', 'Radiology', 'Neuroradiology', 18, 10321, '9804056012', 'short'),
    ('Gita', 'Parajuli', 'Female', 'Pathology', 'Clinical Biochemistry', 11, 13098, '9842167123', 'day'),
    ('Narayan', 'Poudyal', 'Male', 'Cardiology', 'Electrophysiology', 28, 7654, '9851278345', 'morning'),
    ('Samjhana', 'Rijal', 'Female', 'Emergency Medicine', 'Toxicology', 5, 17098, '9862389456', 'emergency'),
    ('Rabin', 'Sigdel', 'Male', 'Neurology', 'Movement Disorders', 10, 13876, '9841490567', 'late'),
    ('Puja', 'Thakuri', 'Female', 'Pediatrics', 'Pediatric Cardiology', 12, 12321, '9806501678', 'day'),
    ('Kishor', 'Wagle', 'Male', 'ENT', 'Head and Neck Surgery', 16, 11098, '9851612789', 'short'),
]


def schedule(shift: str) -> dict:
    hours, closed = SHIFTS[shift]
    return {day: 'closed' if day in closed else hours for day in WEEKDAY_NAMES}


def birth_date(years: int, n: int) -> str:
    """About 26 at graduation, plus experience; month and day vary so no two doctors share a birthday."""
    return f'{2026 - 26 - years - n % 3}-{n % 12 + 1:02d}-{(n * 7) % 27 + 1:02d}'


class Command(BaseCommand):
    help = 'Register 50 doctors spread over all departments (validated like the admin form).'

    def add_arguments(self, parser):
        parser.add_argument('--password', help='One password for every doctor (default: a generated one each).')
        parser.add_argument('--remove', action='store_true', help='Delete the doctors this command registers.')

    def handle(self, *args, **opts):
        licences = [f'NMC-{d[6]}' for d in DOCTORS]
        if opts['remove']:
            users = User.objects.filter(doctor_profile__license_number__in=licences)
            n = users.count()
            users.delete()                       # cascades to the doctor profile and schedules
            self.stdout.write(self.style.SUCCESS(f'Removed {n} doctors.'))
            return

        admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by('id').first()
        created, skipped = [], 0
        with transaction.atomic():
            for n, (first, last, gender, dept, spec, years, nmc, phone, shift) in enumerate(DOCTORS):
                if Doctor.objects.filter(license_number=f'NMC-{nmc}').exists():
                    skipped += 1
                    continue
                data = {
                    'first_name': first, 'last_name': last, 'gender': gender,
                    'department': dept, 'specialization': spec, 'experience_years': years,
                    'license_number': str(nmc), 'phone': phone,
                    'email': f'{first}.{last}@example.com'.lower(),
                    'dob': birth_date(years, n), 'status': 'Active',
                    'availability_schedule': schedule(shift),
                }
                if opts['password']:
                    data['password'] = opts['password']
                serializer = DoctorSerializer(data=data)
                if not serializer.is_valid():
                    raise CommandError(f'Dr. {first} {last}: {serializer.errors}')
                doctor = serializer.save()
                AuditLog.objects.create(
                    user=admin, action='CREATE_DOCTOR',
                    description=f'Created Doctor profile: {doctor.doctor_id} for user {doctor.user.username} '
                                f'(register_doctors command).')
                password = opts['password'] or doctor._generated_password
                created.append((doctor.user.username, password, dept, f'Dr. {first} {last}'))

        self.stdout.write(self.style.SUCCESS(f'Registered {len(created)} doctors ({skipped} already registered, skipped).'))
        if created:
            self.stdout.write('Logins (shown once; each doctor must change the password at first login):')
            width = max(len(u) for u, *_ in created)
            for username, password, dept, name in created:
                self.stdout.write(f'  {username:<{width}}  {password}  {dept:<18}  {name}')
