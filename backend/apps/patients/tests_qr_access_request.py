"""Someone who scans a QR card asks for more information; only an admin's approval reveals it,
only to that requester, and only for QR_ACCESS_HOURS."""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.notifications.models import Notification
from apps.patients.models import QrAccessRequest
from apps.users.factories import make_admin, make_doctor, make_patient

REQUEST = {'requester_name': 'Sita Paramedic', 'requester_phone': '9812345678',
           'reason': 'Found unconscious near the bus park, need allergies before treatment.'}


@override_settings(SECURE_SSL_REDIRECT=False, QR_ACCESS_HOURS=24)
class QrAccessRequestTests(TestCase):
    def setUp(self):
        cache.clear()   # rate limits
        self.patient = make_patient(allergies='Penicillin', current_medication='Metformin 500 mg',
                                    hemoglobin='13.40', blood_pressure='120/80')
        self.admin = make_admin()
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.public = APIClient()

    def _url(self, uuid=None):
        return f'/api/v1/patients/public/{uuid or self.patient.uuid_token}/access-requests/'

    def _create(self, **data):
        return self.public.post(self._url(), {**REQUEST, **data}, format='json')

    def _status(self, token, uuid=None):
        return self.public.get(f'{self._url(uuid)}{token}/')

    def _approve(self, token):
        pk = QrAccessRequest.objects.get(token=token).pk
        return self.admin_client.post(f'/api/v1/qr-access-requests/{pk}/approve/')

    # ── asking ───────────────────────────────────────────────────────────

    def test_request_is_pending_and_admins_are_notified(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'PENDING')
        self.assertTrue(Notification.objects.filter(receiver=self.admin, title='QR Card Access Request').exists())
        r = self._status(r.data['token'])
        self.assertEqual(r.data['status'], 'PENDING')
        self.assertNotIn('record', r.data)

    def test_requester_details_are_validated(self):
        r = self._create(requester_phone='12345', reason='hi', requester_name=' ')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.data), {'requester_phone', 'reason', 'requester_name'})

    def test_second_pending_request_from_same_phone_is_refused(self):
        self.assertEqual(self._create().status_code, 201)
        self.assertEqual(self._create().status_code, 409)

    def test_unknown_card(self):
        r = self.public.post(self._url('00000000-0000-0000-0000-000000000000'), REQUEST, format='json')
        self.assertEqual(r.status_code, 404)

    def test_requests_are_rate_limited(self):
        codes = [self._create(requester_phone=f'98000000{i:02d}').status_code for i in range(7)]
        self.assertEqual(codes[:5], [201] * 5)
        self.assertEqual(codes[5:], [429, 429])

    # ── deciding ─────────────────────────────────────────────────────────

    def test_approved_request_shows_extra_information_for_24_hours(self):
        token = self._create().data['token']
        r = self._approve(token)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['is_active'])

        data = self._status(token).data
        self.assertEqual(data['status'], 'APPROVED')
        record = data['record']
        self.assertEqual(record['medical']['allergies'], 'Penicillin')
        self.assertEqual(record['medical']['current_medication'], 'Metformin 500 mg')
        self.assertEqual(record['contact']['phone'], self.patient.phone)
        self.assertEqual(record['body']['blood_pressure'], '120/80')
        self.assertIn('hemoglobin', [t['test'] for t in record['lab_results']])
        access = QrAccessRequest.objects.get(token=token)
        self.assertAlmostEqual(access.expires_at - access.resolved_at, timedelta(hours=24), delta=timedelta(seconds=1))
        self.assertTrue(Notification.objects.filter(receiver=self.patient.user,
                                                    title='Your Card Information Was Shared').exists())

    def test_access_ends_when_it_expires(self):
        token = self._create().data['token']
        self._approve(token)
        QrAccessRequest.objects.filter(token=token).update(expires_at=timezone.now() - timedelta(seconds=1))
        data = self._status(token).data
        self.assertEqual(data['status'], 'EXPIRED')
        self.assertNotIn('record', data)

    def test_declined_request_shows_nothing_more(self):
        token = self._create().data['token']
        pk = QrAccessRequest.objects.get(token=token).pk
        self.assertEqual(self.admin_client.post(f'/api/v1/qr-access-requests/{pk}/decline/').status_code, 200)
        data = self._status(token).data
        self.assertEqual(data['status'], 'DECLINED')
        self.assertNotIn('record', data)
        self.assertEqual(self._approve(token).status_code, 400)   # already resolved

    def test_admin_can_end_access_early(self):
        token = self._create().data['token']
        self._approve(token)
        pk = QrAccessRequest.objects.get(token=token).pk
        self.assertEqual(self.admin_client.post(f'/api/v1/qr-access-requests/{pk}/revoke/').status_code, 200)
        self.assertEqual(self._status(token).data['status'], 'EXPIRED')

    # ── who can see what ─────────────────────────────────────────────────

    def test_only_the_requester_token_reveals_the_record(self):
        token = self._create().data['token']
        self._approve(token)
        public = self.public.get(f'/api/v1/patients/public/{self.patient.uuid_token}/').data
        self.assertNotIn('allergies', public)
        self.assertEqual(self._status('6f1c2a3b-0000-4000-8000-000000000001').status_code, 404)

    def test_token_only_works_with_its_own_card(self):
        token = self._create().data['token']
        self._approve(token)
        other = make_patient(username='pat2', phone='9800000011', emergency='9800000012')
        self.assertEqual(self._status(token, uuid=other.uuid_token).status_code, 404)

    def test_new_qr_after_lost_card_ends_old_requests(self):
        approved = self._create().data['token']
        self._approve(approved)
        pending = self._create(requester_phone='9812340000').data['token']
        old_card = self.patient.uuid_token
        self.admin_client.post(f'/api/v1/patients/{self.patient.id}/regenerate_qr/')
        self.patient.refresh_from_db()
        # The old card's links stop working altogether...
        self.assertEqual(self._status(approved, uuid=old_card).status_code, 404)
        # ...and the requests made through it give nothing with the new card either.
        self.assertEqual(self._status(approved, uuid=self.patient.uuid_token).data['status'], 'EXPIRED')
        self.assertEqual(self._status(pending, uuid=self.patient.uuid_token).data['status'], 'DECLINED')

    def test_only_admins_list_and_decide(self):
        token = self._create().data['token']
        pk = QrAccessRequest.objects.get(token=token).pk
        doctor = APIClient()
        doctor.force_authenticate(make_doctor().user)
        self.assertEqual(doctor.get('/api/v1/qr-access-requests/').status_code, 403)
        self.assertEqual(doctor.post(f'/api/v1/qr-access-requests/{pk}/approve/').status_code, 403)
        self.assertEqual(self.public.get('/api/v1/qr-access-requests/').status_code, 401)
        listed = self.admin_client.get('/api/v1/qr-access-requests/', {'status': 'PENDING'}).data
        rows = listed['results'] if isinstance(listed, dict) else listed
        self.assertEqual([row['requester_name'] for row in rows], ['Sita Paramedic'])
