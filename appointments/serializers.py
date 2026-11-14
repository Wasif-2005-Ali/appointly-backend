import re

from rest_framework import serializers

from common.user_ids import UserIdField
from .models import Appointment


class OffsetDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, value):
        if not isinstance(value, str) or not re.search(
            r"(?:[zZ]|[+-]\d{2}:\d{2})$", value.strip()
        ):
            raise serializers.ValidationError(
                "Use an ISO 8601 date-time with a UTC offset, for example 2026-11-14T09:00:00Z."
            )
        return super().to_internal_value(value)


class AppointmentCreateSerializer(serializers.Serializer):
    provider_id = UserIdField()
    starts_at = OffsetDateTimeField()
    ends_at = OffsetDateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError(
                {"ends_at": "End time must be later than start time."}
            )
        return attrs


class AppointmentRescheduleSerializer(serializers.Serializer):
    starts_at = OffsetDateTimeField()
    ends_at = OffsetDateTimeField()

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError(
                {"ends_at": "End time must be later than start time."}
            )
        return attrs


class AppointmentSerializer(serializers.ModelSerializer):
    requester_id = UserIdField(read_only=True)
    provider_id = UserIdField(read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "requester_id",
            "provider_id",
            "starts_at",
            "ends_at",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
