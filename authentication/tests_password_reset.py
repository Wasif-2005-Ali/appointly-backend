from urllib.parse import urlsplit, parse_qs

from django.core import mail
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from .models import User


@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
        }
    }
)
class PasswordResetTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="reset.test@example.com",
            full_name="Reset Test",
            profession="Student",
            password="OldSecurePass!2026",
        )
        mail.outbox.clear()

    def request_reset_link(self):
        response = self.client.post(
            "/api/v1/auth/password-reset/",
            {"email": self.user.email},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

        link = mail.outbox[0].body.splitlines()
        reset_url = next(
            line for line in link if "uid=" in line and "token=" in line
        )
        query = parse_qs(urlsplit(reset_url).query)

        return query["uid"][0], query["token"][0]

    def test_password_reset_email_is_sent(self):
        response = self.client.post(
            "/api/v1/auth/password-reset/",
            {"email": self.user.email},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Password Reset", mail.outbox[0].subject)

    def test_unknown_email_does_not_send_email(self):
        response = self.client.post(
            "/api/v1/auth/password-reset/",
            {"email": "unknown@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_password_can_be_reset_and_token_cannot_be_reused(self):
        uid, token = self.request_reset_link()

        payload = {
            "uid": uid,
            "token": token,
            "new_password": "NewSecurePass!2026",
            "confirm_password": "NewSecurePass!2026",
        }

        response = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSecurePass!2026"))
        self.assertFalse(self.user.check_password("OldSecurePass!2026"))

        second_response = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            payload,
            format="json",
        )
        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_invalid_token_is_rejected(self):
        uid, token = self.request_reset_link()

        response = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {
                "uid": uid,
                "token": "invalid-token",
                "new_password": "NewSecurePass!2026",
                "confirm_password": "NewSecurePass!2026",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_password_mismatch_is_rejected(self):
        uid, token = self.request_reset_link()

        response = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {
                "uid": uid,
                "token": token,
                "new_password": "NewSecurePass!2026",
                "confirm_password": "DifferentSecurePass!2026",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
