"""Django email backend that sends via the Mailjet HTTPS API.

Render's free tier cannot reach Gmail's SMTP server (OSError: [Errno 101]
Network is unreachable, Nov 2026), so mail goes over HTTPS instead.
Requires MAILJET_API_KEY and MAILJET_API_SECRET in settings/env. The
sender address is the Mailjet-verified sender (DEFAULT_FROM_EMAIL).
"""

import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

MAILJET_API_URL = "https://api.mailjet.com/v3.1/send"


class MailjetBackend(BaseEmailBackend):
    """Send email through Mailjet's v3.1 Send API."""

    def send_messages(self, email_messages):
        api_key = getattr(settings, "MAILJET_API_KEY", "")
        api_secret = getattr(settings, "MAILJET_API_SECRET", "")
        if not api_key or not api_secret:
            logger.error(
                "MAILJET_API_KEY/MAILJET_API_SECRET not set; email not sent."
            )
            return 0
        sent = 0
        for message in email_messages:
            payload = {
                "Messages": [
                    {
                        "From": {
                            "Email": (
                                message.from_email
                                or settings.DEFAULT_FROM_EMAIL
                            ),
                            "Name": "Appointly",
                        },
                        "To": [{"Email": addr} for addr in message.to],
                        "Subject": message.subject,
                        "TextPart": message.body,
                    }
                ]
            }
            if message.cc:
                payload["Messages"][0]["Cc"] = [
                    {"Email": addr} for addr in message.cc
                ]
            if message.bcc:
                payload["Messages"][0]["Bcc"] = [
                    {"Email": addr} for addr in message.bcc
                ]
            try:
                response = requests.post(
                    MAILJET_API_URL,
                    json=payload,
                    auth=(api_key, api_secret),
                    timeout=30,
                )
            except requests.RequestException:
                logger.exception("Mailjet request failed for %s", message.to)
                continue
            if response.status_code == 200:
                try:
                    status = response.json()["Messages"][0]["Status"]
                except (ValueError, KeyError, IndexError, TypeError):
                    status = None
                if status == "success":
                    sent += 1
                else:
                    logger.error(
                        "Mailjet did not accept mail to %s: %s",
                        message.to,
                        response.text,
                    )
            else:
                logger.error(
                    "Mailjet rejected mail to %s: %s %s",
                    message.to,
                    response.status_code,
                    response.text,
                )
        return sent
