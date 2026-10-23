"""The per-user upload limit (LAB_UPLOAD_THROTTLE_RATE) is really applied."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.lab_reports.views import UploadThrottle
from apps.users.factories import make_patient


@override_settings(SECURE_SSL_REDIRECT=False)
class UploadThrottleTests(TestCase):
    def test_uploads_beyond_the_rate_are_refused(self):
        cache.clear()
        client = APIClient()
        client.force_authenticate(make_patient().user)
        with patch.object(UploadThrottle, 'THROTTLE_RATES', {'lab_upload': '2/hour'}):
            codes = [client.post('/api/v1/lab-reports/', {}, format='multipart').status_code for _ in range(3)]
        self.assertNotEqual(codes[0], 429)
        self.assertNotEqual(codes[1], 429)
        self.assertEqual(codes[2], 429)
