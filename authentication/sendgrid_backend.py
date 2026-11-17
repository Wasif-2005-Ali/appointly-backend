"""Django email backend that sends via the SendGrid HTTPS API.

Render's free tier cannot reach Gmail's SMTP server (OSError: [Errno 101]
Network is unreachable, Nov 2026), so mail goes over HTTPS instead.
Requires SENDGRID_API_KEY in settings/env. The sender address is the
verified SendGrid single sender (DEFAULT_FROM_EMAIL).
"""

import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class SendGridBackend(BaseEmailBackend):
    """Send email through SendGrid's v3 Mail Send API."""

    def send_messages(self, email_messages):
        api_key = getattr(settings, "SENDGRID_API_KEY", "")
        if not api_key:
            logger.error("SENDGRID_API_KEY is not set; email not sent.")
            return 0
        sent = 0
        for message in email_messages:
            personalization = {
                "to": [{"email": addr} for addr in message.to],
            }
            if message.cc:
                personalization["cc"] = [
                    {"email": addr} for addr in message.cc
                ]
            if message.bcc:
                personalization["bcc"] = [
                    {"email": addr} for addr in message.bcc
                ]
            payload = {
                "personalizations": [personalization],
                "from": {
                    "email": message.from_email or settings.DEFAULT_FROM_EMAIL
                },
                "subject": message.subject,
                "content": [{"type": "text/plain", "value": message.body}],
            }
            try:
                response = requests.post(
                    SENDGRID_API_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=30,
                )
            except requests.RequestException:
                logger.exception("SendGrid request failed for %s", message.to)
                continue
            if response.status_code == 202:
                sent += 1
            else:
                logger.error(
                    "SendGrid rejected mail to %s: %s %s",
                    message.to,
                    response.status_code,
                    response.text,
                )
        return sent
