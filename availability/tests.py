from datetime import datetime, time, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from appointments.models import Appointment
from .models import WeeklyAvailability, WeeklyAvailabilityRule


class AvailabilityApiTests(TestCase):
    def setUp(self):
        self.provider = get_user_model().objects.create_user(email="provider@test.com", full_name="Provider", profession="Tester", password="TestPass123!")
        self.client = APIClient()
        self.authenticate_as(self.provider)

    def authenticate_as(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_provider_can_replace_weekly_schedule(self):
        response = self.client.put(
            "/api/v1/availability/me/",
            {
                "timezone": "Asia/Karachi",
                "rules": [
                    {"weekday": 0, "starts_at": "09:00", "ends_at": "12:00"},
                    {"weekday": 4, "starts_at": "13:00", "ends_at": "17:00"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        schedule = WeeklyAvailability.objects.get(provider_id=str(self.provider.pk))
        self.assertEqual(schedule.timezone, "Asia/Karachi")
        self.assertEqual(schedule.rules.count(), 2)

    def test_overlapping_rules_are_rejected(self):
        response = self.client.put(
            "/api/v1/availability/me/",
            {
                "timezone": "UTC",
                "rules": [
                    {"weekday": 0, "starts_at": "09:00", "ends_at": "12:00"},
                    {"weekday": 0, "starts_at": "11:00", "ends_at": "13:00"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(WeeklyAvailability.objects.exists())

    def test_slot_lookup_is_public_and_excludes_existing_bookings(self):
        self.client.credentials()
        day = (timezone.now() + timedelta(days=2)).date()
        schedule = WeeklyAvailability.objects.create(
            provider_id=str(self.provider.pk), timezone="UTC"
        )
        WeeklyAvailabilityRule.objects.create(
            schedule=schedule,
            weekday=day.weekday(),
            starts_at=time(9),
            ends_at=time(11),
        )
        starts_at = datetime.combine(
            day, time(9), tzinfo=datetime_timezone.utc
        )
        Appointment.objects.create(
            requester_id=str(self.provider.pk),
            provider_id="another-user",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=Appointment.Status.ACCEPTED,
        )

        response = self.client.get(
            "/api/v1/availability/slots/",
            {"provider_id": str(self.provider.pk), "date": day.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["slots"]), 3)
        self.assertNotEqual(
            response.data["slots"][0]["starts_at"],
            starts_at.isoformat().replace("+00:00", "Z"),
        )
