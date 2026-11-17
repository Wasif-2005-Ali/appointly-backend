from datetime import datetime, time, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from availability.models import WeeklyAvailability, WeeklyAvailabilityRule
from .models import Appointment


class AppointmentApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.requester = user_model.objects.create_user(email="requester@test.com", full_name="Requester", profession="Tester", password="TestPass123!")
        self.provider = user_model.objects.create_user(email="provider@test.com", full_name="Provider", profession="Tester", password="TestPass123!")
        self.client = APIClient()
        self.authenticate_as(self.requester)

        self.appointment_day = (timezone.now() + timedelta(days=2)).date()
        schedule = WeeklyAvailability.objects.create(
            provider_id=str(self.provider.pk), timezone="UTC"
        )
        WeeklyAvailabilityRule.objects.create(
            schedule=schedule,
            weekday=self.appointment_day.weekday(),
            starts_at=time(9),
            ends_at=time(11),
        )

    def authenticate_as(self, user):
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def future_interval(self):
        starts_at = datetime.combine(
            self.appointment_day, time(9), tzinfo=datetime_timezone.utc
        )
        ends_at = starts_at + timedelta(minutes=30)
        return starts_at.isoformat(), ends_at.isoformat()

    def test_create_uses_simplejwt_identity_and_ignores_client_requester_id(self):
        starts_at, ends_at = self.future_interval()
        response = self.client.post(
            "/api/v1/appointments/",
            {
                "requester_id": "forged",
                "provider_id": str(self.provider.pk),
                "starts_at": starts_at,
                "ends_at": ends_at,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.requester_id, str(self.requester.pk))
        self.assertEqual(response.data["requester_id"], str(self.requester.pk))

    def test_overlapping_booking_returns_conflict(self):
        starts_at, ends_at = self.future_interval()
        Appointment.objects.create(
            requester_id="another-user",
            provider_id=str(self.provider.pk),
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
        )

        response = self.client.post(
            "/api/v1/appointments/",
            {
                "provider_id": str(self.provider.pk),
                "starts_at": starts_at,
                "ends_at": ends_at,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_only_provider_can_accept_appointment(self):
        starts_at, ends_at = self.future_interval()
        appointment = Appointment.objects.create(
            requester_id=str(self.requester.pk),
            provider_id=str(self.provider.pk),
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
        )

        response = self.client.post(
            f"/api/v1/appointments/{appointment.pk}/accept/", {}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.PENDING)

    def test_provider_can_accept_pending_appointment(self):
        starts_at, ends_at = self.future_interval()
        appointment = Appointment.objects.create(
            requester_id=str(self.requester.pk),
            provider_id=str(self.provider.pk),
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
        )
        self.authenticate_as(self.provider)

        response = self.client.post(
            f"/api/v1/appointments/{appointment.pk}/accept/", {}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.ACCEPTED)

    # -- complete endpoint -------------------------------------------------

    def _accepted_appointment(self):
        starts_at, ends_at = self.future_interval()
        return Appointment.objects.create(
            requester_id=str(self.requester.pk),
            provider_id=str(self.provider.pk),
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
            status=Appointment.Status.ACCEPTED,
        )

    def test_provider_can_complete_accepted_appointment(self):
        appointment = self._accepted_appointment()
        self.authenticate_as(self.provider)

        response = self.client.post(
            f"/api/v1/appointments/{appointment.pk}/complete/", {}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)

    def test_complete_requires_accepted_status(self):
        starts_at, ends_at = self.future_interval()
        appointment = Appointment.objects.create(
            requester_id=str(self.requester.pk),
            provider_id=str(self.provider.pk),
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
        )
        self.authenticate_as(self.provider)

        response = self.client.post(
            f"/api/v1/appointments/{appointment.pk}/complete/", {}, format="json"
        )

        self.assertEqual(response.status_code, 409)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.PENDING)

    def test_only_provider_can_complete_appointment(self):
        appointment = self._accepted_appointment()

        response = self.client.post(
            f"/api/v1/appointments/{appointment.pk}/complete/", {}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.ACCEPTED)

    # -- delete endpoint ---------------------------------------------------

    def test_participant_can_delete_pending_appointment(self):
        starts_at, ends_at = self.future_interval()
        appointment = Appointment.objects.create(
            requester_id=str(self.requester.pk),
            provider_id=str(self.provider.pk),
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
        )

        response = self.client.delete(f"/api/v1/appointments/{appointment.pk}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Appointment.objects.filter(pk=appointment.pk).exists())

    def test_non_participant_cannot_delete_appointment(self):
        user_model = get_user_model()
        outsider = user_model.objects.create_user(
            email="outsider@test.com", full_name="Outsider",
            profession="Tester", password="TestPass123!",
        )
        starts_at, ends_at = self.future_interval()
        appointment = Appointment.objects.create(
            requester_id=str(self.requester.pk),
            provider_id=str(self.provider.pk),
            starts_at=datetime.fromisoformat(starts_at),
            ends_at=datetime.fromisoformat(ends_at),
        )
        self.authenticate_as(outsider)

        response = self.client.delete(f"/api/v1/appointments/{appointment.pk}/")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Appointment.objects.filter(pk=appointment.pk).exists())

    def test_completed_appointment_cannot_be_deleted(self):
        appointment = self._accepted_appointment()
        appointment.status = Appointment.Status.COMPLETED
        appointment.save(update_fields=["status"])

        response = self.client.delete(f"/api/v1/appointments/{appointment.pk}/")

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Appointment.objects.filter(pk=appointment.pk).exists())

    def test_delete_missing_appointment_returns_404(self):
        response = self.client.delete("/api/v1/appointments/999999/")

        self.assertEqual(response.status_code, 404)
