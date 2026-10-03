from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.recommendations.views import mentions, score_departments
from apps.users.factories import make_doctor

PRIVATE_DOCTOR_FIELDS = ('phone', 'email', 'dob', 'license_number', 'login_username', 'user_id', 'user')


@override_settings(SECURE_SSL_REDIRECT=False)
class SymptomCheckerPrivacyTests(TestCase):
    def test_anonymous_result_has_no_doctor_personal_data(self):
        make_doctor()
        r = APIClient().post(
            '/api/v1/recommendations/',
            {'symptoms': 'chest pain and palpitation', 'pain_level': 5},
            format='json',
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['ranked_doctors'])
        for doc in r.data['ranked_doctors']:
            for key in PRIVATE_DOCTOR_FIELDS:
                self.assertNotIn(key, doc)
        for key in PRIVATE_DOCTOR_FIELDS:
            self.assertNotIn(key, r.data['recommended_doctor_detail'])


class SymptomMatchingTests(TestCase):
    def test_whole_words_only(self):
        self.assertFalse(mentions('ear', 'my heart hurts'))
        self.assertFalse(mentions('bp', 'subpar sleep'))
        self.assertTrue(mentions('chest pain', 'severe chest pain since morning'))

    def test_negated_symptoms_ignored(self):
        self.assertFalse(mentions('chest pain', 'no chest pain'))
        self.assertFalse(mentions('fever', 'without fever'))
        self.assertTrue(mentions('headache', 'no fever but a bad headache'))

    def test_negation_changes_department(self):
        scores = score_departments('no chest pain, but a rash on my skin')
        self.assertNotIn('Cardiology', scores)
        self.assertIn('Dermatology', scores)
