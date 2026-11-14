from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ValueError, KeyError) as exc:
        raise ValidationError("Enter a valid IANA time zone, such as Asia/Karachi.") from exc


class WeeklyAvailability(models.Model):
    provider_id = models.CharField(max_length=255, unique=True)
    timezone = models.CharField(
        max_length=64, default="UTC", validators=[validate_timezone]
    )
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def zone(self):
        return ZoneInfo(self.timezone)

    def __str__(self):
        return f"Availability for {self.provider_id}"


class WeeklyAvailabilityRule(models.Model):
    schedule = models.ForeignKey(
        WeeklyAvailability, related_name="rules", on_delete=models.CASCADE
    )
    weekday = models.PositiveSmallIntegerField()
    starts_at = models.TimeField()
    ends_at = models.TimeField()

    class Meta:
        ordering = ["weekday", "starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(weekday__gte=0) & Q(weekday__lte=6),
                name="availability_weekday_0_to_6",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="availability_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["schedule", "weekday", "starts_at", "ends_at"],
                name="unique_availability_rule",
            ),
        ]
