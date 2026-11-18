import re

from django.contrib.auth import get_user_model
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
    # Full display names so the app can show real names instead of
    # "Provider #<id>". Null when the user no longer exists; the app
    # falls back to the id in that case.
    requester_name = serializers.SerializerMethodField()
    provider_name = serializers.SerializerMethodField()

    def _full_name_for(self, user_id):
        """Look up a user's full_name, cached per serializer instance
        so a list response does one query per distinct user."""
        cache = getattr(self, "_name_cache", None)
        if cache is None:
            cache = self._name_cache = {}
        if user_id not in cache:
            User = get_user_model()
            try:
                cache[user_id] = User.objects.get(pk=user_id).full_name
            except (User.DoesNotExist, ValueError):
                cache[user_id] = None
        return cache[user_id]

    def get_requester_name(self, obj):
        return self._full_name_for(obj.requester_id)

    def get_provider_name(self, obj):
        return self._full_name_for(obj.provider_id)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "requester_id",
            "requester_name",
            "provider_id",
            "provider_name",
            "starts_at",
            "ends_at",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
