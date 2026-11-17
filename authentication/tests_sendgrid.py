"""Tests for the SendGrid HTTPS email backend and for the reset view
staying up (200) when mail delivery fails."""

from unittest.mock import patch

import requests
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from .models import User
from .sendgrid_backend import SendGridBackend


class SendGridBackendTests(TestCase):
    def setUp(self):
        self.backend = SendGridBackend()
        self.message = EmailMessage(
            subject="Appointly Password Reset",
            body="Hello, reset link here.",
            from_email="bestwasifali@gmail.com",
            to=["user@example.com"],
        )

    @override_settings(SENDGRID_API_KEY="SG.test-key")
    @patch("authentication.sendgrid_backend.requests.post")
    def test_accepted_mail_counts_as_sent(self, mock_post):
        mock_post.return_value.status_code = 202
        mock_post.return_value.text = ""

        sent = self.backend.send_messages([self.message])

        self.assertEqual(sent, 1)
        _, kwargs = mock_post.call_args
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Bearer SG.test-key"
        )
        payload = kwargs["json"]
        self.assertEqual(payload["subject"], "Appointly Password Reset")
        self.assertEqual(
            payload["personalizations"][0]["to"],
            [{"email": "user@example.com"}],
        )
        self.assertEqual(
            payload["from"], {"email": "bestwasifali@gmail.com"}
        )

    @override_settings(SENDGRID_API_KEY="SG.test-key")
    @patch("authentication.sendgrid_backend.requests.post")
    def test_rejected_mail_counts_as_unsent(self, mock_post):
        mock_post.return_value.status_code = 403
        mock_post.return_value.text = "forbidden"

        sent = self.backend.send_messages([self.message])

        self.assertEqual(sent, 0)

    @override_settings(SENDGRID_API_KEY="SG.test-key")
    @patch(
        "authentication.sendgrid_backend.requests.post",
        side_effect=requests.exceptions.ConnectionError(
            "Network is unreachable"
        ),
    )
    def test_network_error_counts_as_unsent(self, mock_post):
        sent = self.backend.send_messages([self.message])
        self.assertEqual(sent, 0)

    @override_settings(SENDGRID_API_KEY="")
    @patch("authentication.sendgrid_backend.requests.post")
    def test_missing_api_key_sends_nothing(self, mock_post):
        sent = self.backend.send_messages([self.message])
        self.assertEqual(sent, 0)
        mock_post.assert_not_called()


class PasswordResetMailFailureTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reset.fail@example.com",
            full_name="Reset Fail",
            profession="Student",
            password="OldSecurePass!2026",
        )

    @patch(
        "authentication.password_reset_views.send_mail",
        side_effect=OSError("Network is unreachable"),
    )
    def test_reset_returns_200_when_mail_fails(self, mock_send):
        response = self.client.post(
            "/api/v1/auth/password-reset/",
            {"email": self.user.email},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
