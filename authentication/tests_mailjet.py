"""Tests for the Mailjet HTTPS email backend."""

from unittest.mock import patch

import requests
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings

from .mailjet_backend import MailjetBackend


@override_settings(
    MAILJET_API_KEY="mj-test-key", MAILJET_API_SECRET="mj-test-secret"
)
class MailjetBackendTests(TestCase):
    def setUp(self):
        self.backend = MailjetBackend()
        self.message = EmailMessage(
            subject="Appointly Password Reset",
            body="Hello, reset link here.",
            from_email="bestwasifali@gmail.com",
            to=["user@example.com"],
        )

    @patch("authentication.mailjet_backend.requests.post")
    def test_accepted_mail_counts_as_sent(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "Messages": [{"Status": "success"}]
        }

        sent = self.backend.send_messages([self.message])

        self.assertEqual(sent, 1)
        _, kwargs = mock_post.call_args
        self.assertEqual(
            kwargs["auth"], ("mj-test-key", "mj-test-secret")
        )
        payload = kwargs["json"]["Messages"][0]
        self.assertEqual(payload["Subject"], "Appointly Password Reset")
        self.assertEqual(payload["To"], [{"Email": "user@example.com"}])
        self.assertEqual(
            payload["From"]["Email"], "bestwasifali@gmail.com"
        )

    @patch("authentication.mailjet_backend.requests.post")
    def test_rejected_mail_counts_as_unsent(self, mock_post):
        mock_post.return_value.status_code = 401
        mock_post.return_value.text = "unauthorized"

        sent = self.backend.send_messages([self.message])

        self.assertEqual(sent, 0)

    @patch("authentication.mailjet_backend.requests.post")
    def test_error_status_counts_as_unsent(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "Messages": [{"Status": "error"}]
        }
        mock_post.return_value.text = '{"Messages": [{"Status": "error"}]}'

        sent = self.backend.send_messages([self.message])

        self.assertEqual(sent, 0)

    @patch(
        "authentication.mailjet_backend.requests.post",
        side_effect=requests.exceptions.ConnectionError(
            "Network is unreachable"
        ),
    )
    def test_network_error_counts_as_unsent(self, mock_post):
        sent = self.backend.send_messages([self.message])
        self.assertEqual(sent, 0)

    @override_settings(MAILJET_API_KEY="", MAILJET_API_SECRET="")
    @patch("authentication.mailjet_backend.requests.post")
    def test_missing_credentials_send_nothing(self, mock_post):
        sent = self.backend.send_messages([self.message])
        self.assertEqual(sent, 0)
        mock_post.assert_not_called()
