from datetime import datetime, timedelta, timezone as datetime_timezone

from django.db.models import Q
from django.utils import timezone

from appointments.models import Appointment
from .models import WeeklyAvailability, WeeklyAvailabilityRule


ACTIVE_STATUSES = [Appointment.Status.PENDING, Appointment.Status.ACCEPTED]


def _localize_slot_start(day, local_time, zone):
    naive = datetime.combine(day, local_time)
    aware = naive.replace(tzinfo=zone, fold=0)
    if aware.astimezone(datetime_timezone.utc).astimezone(zone).replace(
        tzinfo=None
    ) != naive:
        return None
    return aware


def get_available_slots(provider_id, day, duration_minutes):
    try:
        schedule = WeeklyAvailability.objects.get(provider_id=provider_id)
    except WeeklyAvailability.DoesNotExist:
        return []

    zone = schedule.zone
    rules = WeeklyAvailabilityRule.objects.filter(
        schedule=schedule, weekday=day.weekday()
    )
    duration = timedelta(minutes=duration_minutes)
    now = timezone.now()
    slots = {}

    for rule in rules:
        local_start = datetime.combine(day, rule.starts_at)
        local_end = datetime.combine(day, rule.ends_at)
        while local_start + duration <= local_end:
            aware_start = _localize_slot_start(day, local_start.time(), zone)
            aware_end = _localize_slot_start(day, (local_start + duration).time(), zone)
            if aware_start is not None and aware_end is not None:
                starts_at = aware_start.astimezone(datetime_timezone.utc)
                ends_at = aware_end.astimezone(datetime_timezone.utc)
                if starts_at > now:
                    has_conflict = Appointment.objects.filter(
                        status__in=ACTIVE_STATUSES,
                        starts_at__lt=ends_at,
                        ends_at__gt=starts_at,
                    ).filter(
                        Q(provider_id=provider_id) | Q(requester_id=provider_id)
                    ).exists()
                    if not has_conflict:
                        slots[starts_at.isoformat()] = {
                            "starts_at": starts_at.isoformat().replace("+00:00", "Z"),
                            "ends_at": ends_at.isoformat().replace("+00:00", "Z"),
                        }
            local_start += duration

    return [slots[key] for key in sorted(slots)]
