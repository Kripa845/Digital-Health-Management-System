from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.users.factories import make_admin, make_patient

NEW_PATIENT = {
    'patient_id': 'PAT-9C0E059C',
    'first_name': 'Ram-Bahadur', 'last_name': "O'Neil", 'dob': '1990-05-05', 'gender': 'Male',
    'blood_group': 'A+', 'phone': '9841000000', 'emergency_contact': '9841000001',
    'email': 'ram@example.com', 'address': 'Ward 4, Lalitpur', 'height': '170', 'weight': '65',
}


@override_settings(SECURE_SSL_REDIRECT=False)
class PublicProfileTests(TestCase):
    def test_public_profile_hides_identity_theft_data(self):
        patient = make_patient()
        data = APIClient().get(f'/api/v1/patients/public/{patient.uuid_token}/').data
        for key in ('dob', 'phone', 'id', 'email', 'address'):
            self.assertNotIn(key, data)
        for key in ('first_name', 'blood_group', 'emergency_contact', 'age'):
            self.assertIn(key, data)

    def test_regenerated_qr_invalidates_old_card(self):
        admin = make_admin()
        patient = make_patient()
        old = patient.uuid_token
        client = APIClient()
        client.force_authenticate(admin)
        r = client.post(f'/api/v1/patients/{patient.id}/regenerate_qr/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(APIClient().get(f'/api/v1/patients/public/{old}/').status_code, 404)
        self.assertEqual(APIClient().get(f"/api/v1/patients/public/{r.data['uuid_token']}/").status_code, 200)

    def test_patient_cannot_regenerate_qr(self):
        patient = make_patient()
        client = APIClient()
        client.force_authenticate(patient.user)
        self.assertEqual(client.post(f'/api/v1/patients/{patient.id}/regenerate_qr/').status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class PatientCreationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(make_admin())

    def test_names_with_hyphen_apostrophe_and_devanagari_accepted(self):
        r = self.client.post('/api/v1/patients/', NEW_PATIENT, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post('/api/v1/patients/', {
            **NEW_PATIENT, 'patient_id': 'PAT-51A00001', 'first_name': 'सीता', 'last_name': 'श्रेष्ठ', 'address': 'काठमाडौं',
            'phone': '9841000002', 'emergency_contact': '9841000003', 'email': 'sita@example.com',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_digits_in_name_rejected(self):
        r = self.client.post('/api/v1/patients/', {**NEW_PATIENT, 'first_name': 'R4m'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_credentials_returned_when_email_fails(self):
        with patch('apps.users.email_service.send_mail', side_effect=OSError('SMTP down')):
            r = self.client.post('/api/v1/patients/', NEW_PATIENT, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data['email_sent'])
        self.assertTrue(r.data['generated_username'])
        self.assertTrue(r.data['generated_password'])

    def test_credentials_not_returned_when_email_sent(self):
        r = self.client.post('/api/v1/patients/', NEW_PATIENT, format='json')
        self.assertTrue(r.data['email_sent'])
        self.assertNotIn('generated_password', r.data)

    def test_all_clinical_fields_exposed(self):
        patient = make_patient(hba1c='6.1', tsh='2.500')
        data = self.client.get(f'/api/v1/patients/{patient.id}/').data
        self.assertEqual(data['hba1c'], '6.10')
        self.assertEqual(data['tsh'], '2.500')


@override_settings(SECURE_SSL_REDIRECT=False)
class PatientPasswordResetTests(TestCase):
    def test_admin_resets_patient_password(self):
        patient = make_patient()
        client = APIClient()
        client.force_authenticate(make_admin())
        r = client.post(f'/api/v1/patients/{patient.id}/reset_password/')
        self.assertEqual(r.status_code, 200)
        patient.user.refresh_from_db()
        self.assertTrue(patient.user.check_password(r.data['new_password']))
        self.assertTrue(patient.user.must_change_password)

    def test_patient_cannot_reset_passwords(self):
        patient = make_patient()
        client = APIClient()
        client.force_authenticate(patient.user)
        self.assertEqual(client.post(f'/api/v1/patients/{patient.id}/reset_password/').status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class PatientSelfEditTests(TestCase):
    def setUp(self):
        self.patient = make_patient()
        self.client = APIClient()
        self.client.force_authenticate(self.patient.user)

    def test_patient_updates_contact_details(self):
        r = self.client.patch('/api/v1/patients/me/', {
            'phone': '9841111111', 'emergency_contact': '9842222222',
            'email': 'new@example.com', 'address': 'Ward 5, Bhaktapur',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone, '9841111111')
        self.assertEqual(self.patient.address, 'Ward 5, Bhaktapur')
        self.assertEqual(self.patient.user.email, 'new@example.com')   # login account kept in sync
        self.assertEqual(r.data['phone'], '9841111111')                 # full profile returned

    def test_identity_and_medical_fields_cannot_be_changed(self):
        r = self.client.patch('/api/v1/patients/me/', {
            'dob': '2000-01-01', 'gender': 'Female', 'blood_group': 'AB-',
            'allergies': '', 'hemoglobin': '9.0', 'status': 'Inactive', 'phone': '9841111111',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.patient.refresh_from_db()
        self.assertEqual(str(self.patient.dob), '1990-01-01')
        self.assertEqual(self.patient.gender, 'Male')
        self.assertEqual(self.patient.blood_group, 'O+')
        self.assertEqual(self.patient.status, 'Active')
        self.assertIsNone(self.patient.hemoglobin)
        self.assertEqual(self.patient.phone, '9841111111')

    def test_validation_errors_returned(self):
        r = self.client.patch('/api/v1/patients/me/', {'phone': '12345'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('phone', r.data)
        # Same as the saved emergency contact
        r = self.client.patch('/api/v1/patients/me/', {'phone': self.patient.emergency_contact}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('emergency_contact', r.data)

    def test_photo_upload(self):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = io.BytesIO()
        Image.new('RGB', (40, 40), 'teal').save(buf, format='PNG')
        with override_settings(MEDIA_ROOT=__import__('tempfile').mkdtemp()):
            r = self.client.patch('/api/v1/patients/me/', {
                'photo': SimpleUploadedFile('me.png', buf.getvalue(), content_type='image/png'),
            }, format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['photo'])

    def test_only_patients_can_use_it(self):
        other = APIClient()
        other.force_authenticate(make_admin())
        self.assertEqual(other.patch('/api/v1/patients/me/', {'phone': '9841111111'}, format='json').status_code, 403)
        self.assertEqual(APIClient().get('/api/v1/patients/me/').status_code, 401)

    def test_patient_still_cannot_use_admin_edit(self):
        r = self.client.patch(f'/api/v1/patients/{self.patient.id}/', {'first_name': 'Someone'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_change_is_audited_without_values(self):
        from apps.audit.models import AuditLog
        self.client.patch('/api/v1/patients/me/', {'phone': '9841111111'}, format='json')
        entry = AuditLog.objects.get(action='UPDATE_OWN_PROFILE')
        self.assertIn('phone', entry.description)
        self.assertNotIn('9841111111', entry.description)


    def test_patient_changes_name(self):
        from apps.notifications.models import Notification
        admin = make_admin()
        r = self.client.patch('/api/v1/patients/me/', {
            'first_name': 'hari', 'middle_name': 'Bahadur', 'last_name': "Tamang-Lama",
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.patient.refresh_from_db()
        user = self.patient.user
        user.refresh_from_db()
        self.assertEqual(self.patient.first_name, 'Hari')              # normalised capital
        self.assertEqual(self.patient.middle_name, 'Bahadur')
        self.assertEqual(self.patient.last_name, 'Tamang-Lama')
        self.assertEqual((user.first_name, user.last_name), ('Hari', 'Tamang-Lama'))   # login account in sync
        self.assertEqual(user.username, 'pat1')                        # still signs in the same way
        note = Notification.objects.get(receiver=admin, title='Patient Changed Their Name')
        self.assertIn('Hari Tamang', note.message)
        self.assertIn('Hari Bahadur Tamang-Lama', note.message)

    def test_invalid_names_rejected(self):
        r = self.client.patch('/api/v1/patients/me/', {'first_name': 'H4ri'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('first_name', r.data)
        r = self.client.patch('/api/v1/patients/me/', {'last_name': 'T'}, format='json')
        self.assertIn('last_name', r.data)

    def test_contact_change_does_not_notify_admins(self):
        from apps.notifications.models import Notification
        make_admin()
        self.client.patch('/api/v1/patients/me/', {'phone': '9841111111'}, format='json')
        self.assertFalse(Notification.objects.filter(title='Patient Changed Their Name').exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class PatientListTests(TestCase):
    def test_newest_patient_first_and_large_pages(self):
        client = APIClient()
        client.force_authenticate(make_admin())
        for i in range(12):
            make_patient(f'p{i}', phone=f'98000001{i:02d}', emergency=f'98000002{i:02d}')
        newest = make_patient('newest', phone='9800000399', emergency='9800000398')

        page = client.get('/api/v1/patients/').data
        self.assertEqual(page['count'], 13)
        self.assertEqual(len(page['results']), 10)                  # default page size
        self.assertEqual(page['results'][0]['patient_id'], newest.patient_id)

        everything = client.get('/api/v1/patients/?page_size=200').data
        self.assertEqual(len(everything['results']), 13)
        self.assertIsNone(everything['next'])


@override_settings(SECURE_SSL_REDIRECT=False)
class PatientIdTests(TestCase):
    """The admin types the patient ID; the QR card is keyed by uuid_token."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(make_admin())

    def create(self, patient_id, **extra):
        return self.client.post('/api/v1/patients/', {**NEW_PATIENT, 'patient_id': patient_id, **extra}, format='json')

    def test_valid_id_is_created_normalised_and_audited(self):
        from apps.audit.models import AuditLog
        from apps.patients.models import Patient

        r = self.create('  pat-ab12cd34 ')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['patient']['patient_id'], 'PAT-AB12CD34')
        patient = Patient.objects.get(patient_id='PAT-AB12CD34')
        self.assertTrue(
            AuditLog.objects.filter(action='CREATE_PATIENT', description__contains='PAT-AB12CD34').exists()
        )
        self.assertEqual(r.data['patient']['uuid_token'], str(patient.uuid_token))

    def test_number_part_alone_is_accepted(self):
        for typed, stored, extra in (
            ('79028232', 'PAT-79028232', {}),
            ('pat 7902 8232', None, {}),   # same code: duplicate
            ('PAT-55555555', 'PAT-55555555',
             {'phone': '9841000020', 'emergency_contact': '9841000021', 'email': 'c@example.com'}),
        ):
            r = self.create(typed, **extra)
            if stored:
                self.assertEqual(r.status_code, 201, r.data)
                self.assertEqual(r.data['patient']['patient_id'], stored)
            else:
                self.assertEqual(r.data['patient_id'], ['A patient with ID PAT-79028232 already exists.'])

    def test_shortest_and_longest_ids_accepted(self):
        self.assertEqual(self.create('PAT-1234').status_code, 201)
        r = self.create('PAT-ABCDEF123456', phone='9841000010', emergency_contact='9841000011', email='b@example.com')
        self.assertEqual(r.status_code, 201, r.data)

    def test_missing_id_rejected(self):
        body = {k: v for k, v in NEW_PATIENT.items() if k != 'patient_id'}
        r = self.client.post('/api/v1/patients/', body, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('patient_id', r.data)

    def test_duplicate_rejected_in_any_letter_case(self):
        make_patient(patient_id='PAT-DUP00001')
        for typed in ('PAT-DUP00001', 'pat-dup00001', 'Pat-Dup00001 '):
            r = self.create(typed)
            self.assertEqual(r.status_code, 400, typed)
            self.assertEqual(r.data['patient_id'], ['A patient with ID PAT-DUP00001 already exists.'])

    def test_invalid_format_rejected(self):
        for typed in ('', 'PAT-', '123', 'PAT-ABC', 'PAT-ABCDEF1234567', 'PAT_AB12CD34', 'PAT-AB12!', 'PAT-ABCD'):
            r = self.create(typed)
            self.assertEqual(r.status_code, 400, typed)
            self.assertIn('patient_id', r.data, typed)

    def test_admin_can_change_patient_id(self):
        from apps.audit.models import AuditLog

        patient = make_patient(patient_id='PAT-OLD00001')
        token = patient.uuid_token
        r = self.client.patch(f'/api/v1/patients/{patient.id}/', {'patient_id': '79028232'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['patient_id'], 'PAT-79028232')
        patient.refresh_from_db()
        self.assertEqual(patient.patient_id, 'PAT-79028232')
        self.assertEqual(patient.uuid_token, token)            # the QR card keeps working
        self.assertTrue(AuditLog.objects.filter(
            action='CHANGE_PATIENT_ID', description='Changed patient ID from PAT-OLD00001 to PAT-79028232.',
        ).exists())

    def test_saving_with_the_same_id_is_allowed(self):
        patient = make_patient(patient_id='PAT-KEEP0001')
        r = self.client.patch(f'/api/v1/patients/{patient.id}/', {'patient_id': 'keep0001', 'address': 'Bhaktapur'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['patient_id'], 'PAT-KEEP0001')

    def test_changing_to_another_patients_id_rejected(self):
        make_patient(patient_id='PAT-TAKE0001')
        patient = make_patient('pat2', phone='9800000003', emergency='9800000004', patient_id='PAT-MINE0001')
        r = self.client.patch(f'/api/v1/patients/{patient.id}/', {'patient_id': 'take0001'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['patient_id'], ['A patient with ID PAT-TAKE0001 already exists.'])
        patient.refresh_from_db()
        self.assertEqual(patient.patient_id, 'PAT-MINE0001')

    def test_patient_cannot_change_own_id(self):
        patient = make_patient(patient_id='PAT-SELF0001')
        client = APIClient()
        client.force_authenticate(patient.user)
        client.patch('/api/v1/patients/me/', {'patient_id': 'PAT-HACK0001'}, format='json')
        self.assertEqual(client.patch(f'/api/v1/patients/{patient.id}/', {'patient_id': '12345678'}, format='json').status_code, 403)
        patient.refresh_from_db()
        self.assertEqual(patient.patient_id, 'PAT-SELF0001')

    def test_model_refuses_a_patient_without_id(self):
        from apps.patients.models import Patient
        with self.assertRaises(ValueError):
            make_patient(patient_id='')
        self.assertFalse(Patient.objects.exists())

    def test_qr_link_uses_uuid_token_not_patient_id(self):
        """The QR encodes /public-profile/<uuid_token>; the patient ID never opens a profile."""
        patient = make_patient(patient_id='PAT-QR000001')
        public = APIClient()
        r = public.get(f'/api/v1/patients/public/{patient.uuid_token}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['patient_id'], 'PAT-QR000001')
        self.assertEqual(public.get('/api/v1/patients/public/PAT-QR000001/').status_code, 404)


    def test_id_needs_at_least_four_digits(self):
        for typed in ('PAT-AB12', 'ABC123', 'PAT-XYZ1'):
            r = self.create(typed)
            self.assertEqual(r.status_code, 400, typed)
            self.assertIn('at least 4 digits', r.data['patient_id'][0])

    def test_number_part_must_be_unique(self):
        """Reports are matched on the digits, so PAT-AB79028232 would clash with PAT-79028232."""
        make_patient(patient_id='PAT-79028232')
        r = self.create('AB79028232')
        self.assertEqual(r.status_code, 400)
        self.assertIn('already uses the number 79028232', r.data['patient_id'][0])
