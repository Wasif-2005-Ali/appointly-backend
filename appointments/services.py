from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import exceptions, status
from rest_framework.exceptions import APIException

from availability.models import WeeklyAvailability, WeeklyAvailabilityRule
from common.locks import lock_users
from .models import Appointment


ACTIVE_STATUSES = [Appointment.Status.PENDING, Appointment.Status.ACCEPTED]


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The requested time conflicts with another appointment."
    default_code = "conflict"


def assert_available(requester_id, provider_id, starts_at, ends_at, exclude_id=None):
    if requester_id == provider_id:
        raise exceptions.ValidationError(
            {"provider_id": "You cannot book an appointment with yourself."}
        )
    if starts_at <= timezone.now():
        raise exceptions.ValidationError(
            {"starts_at": "The appointment must start in the future."}
        )

    try:
        schedule = WeeklyAvailability.objects.get(provider_id=provider_id)
    except WeeklyAvailability.DoesNotExist as exc:
        raise exceptions.ValidationError(
            {"provider_id": "This provider has not published availability."}
        ) from exc

    local_start = starts_at.astimezone(schedule.zone)
    local_end = ends_at.astimezone(schedule.zone)
    if local_start.date() != local_end.date():
        raise exceptions.ValidationError(
            {"ends_at": "An appointment must fit within one local calendar day."}
        )

    weekday_rules = WeeklyAvailabilityRule.objects.filter(
        schedule=schedule, weekday=local_start.weekday()
    )
    fits_schedule = any(
        local_start.time().replace(tzinfo=None) >= rule.starts_at
        and local_end.time().replace(tzinfo=None) <= rule.ends_at
        for rule in weekday_rules
    )
    if not fits_schedule:
        raise exceptions.ValidationError(
            {"starts_at": "The requested time is outside the provider's availability."}
        )

    participants = [requester_id, provider_id]
    overlaps = Appointment.objects.filter(
        status__in=ACTIVE_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).filter(Q(provider_id__in=participants) | Q(requester_id__in=participants))
    if exclude_id is not None:
        overlaps = overlaps.exclude(pk=exclude_id)
    if overlaps.exists():
        raise Conflict()


@transaction.atomic
def create_appointment(requester_id, provider_id, starts_at, ends_at, notes=""):
    lock_users([requester_id, provider_id])
    assert_available(requester_id, provider_id, starts_at, ends_at)
    return Appointment.objects.create(
        requester_id=requester_id,
        provider_id=provider_id,
        starts_at=starts_at,
        ends_at=ends_at,
        notes=notes,
    )


@transaction.atomic
def reschedule_appointment(appointment_id, user_id, starts_at, ends_at):
    appointment = get_object_or_404(Appointment, pk=appointment_id)
    lock_users([appointment.requester_id, appointment.provider_id])
    appointment = Appointment.objects.select_for_update().get(pk=appointment_id)
    if appointment.requester_id != user_id:
        raise exceptions.PermissionDenied("Only the requester can reschedule this appointment.")
    if appointment.status not in ACTIVE_STATUSES:
        raise Conflict("Only pending or accepted appointments can be rescheduled.")

    assert_available(
        appointment.requester_id,
        appointment.provider_id,
        starts_at,
        ends_at,
        exclude_id=appointment.pk,
    )
    appointment.starts_at = starts_at
    appointment.ends_at = ends_at
    appointment.save(update_fields=["starts_at", "ends_at", "updated_at"])
    return appointment


@transaction.atomic
def transition_appointment(appointment_id, user_id, action):
    appointment = get_object_or_404(Appointment, pk=appointment_id)
    lock_users([appointment.requester_id, appointment.provider_id])
    appointment = Appointment.objects.select_for_update().get(pk=appointment_id)

    if user_id not in {appointment.requester_id, appointment.provider_id}:
        raise exceptions.PermissionDenied("You are not a participant in this appointment.")

    if action in {"accept", "reject"}:
        if user_id != appointment.provider_id:
            raise exceptions.PermissionDenied("Only the provider can respond to a request.")
        if appointment.status != Appointment.Status.PENDING:
            raise Conflict("Only pending appointments can be accepted or rejected.")
        appointment.status = (
            Appointment.Status.ACCEPTED
            if action == "accept"
            else Appointment.Status.REJECTED
        )
    elif action == "cancel":
        if appointment.status not in ACTIVE_STATUSES:
            raise Conflict("Only pending or accepted appointments can be cancelled.")
        appointment.status = Appointment.Status.CANCELLED
    elif action == "complete":
        # Only the provider marks an appointment complete: the provider
        # delivers the service, so only they can confirm it happened.
        if user_id != appointment.provider_id:
            raise exceptions.PermissionDenied(
                "Only the provider can mark an appointment as completed."
            )
        if appointment.status != Appointment.Status.ACCEPTED:
            raise Conflict("Only accepted appointments can be marked as completed.")
        appointment.status = Appointment.Status.COMPLETED
    else:
        raise ValueError(f"Unsupported appointment action: {action}")

    appointment.save(update_fields=["status", "updated_at"])
    return appointment
