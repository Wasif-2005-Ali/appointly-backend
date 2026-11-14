from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from common.user_ids import UserIdField
from .models import WeeklyAvailabilityRule


class AvailabilityRuleInputSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    starts_at = serializers.TimeField(format="%H:%M", input_formats=["%H:%M", "%H:%M:%S"])
    ends_at = serializers.TimeField(format="%H:%M", input_formats=["%H:%M", "%H:%M:%S"])

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError(
                {"ends_at": "End time must be later than start time."}
            )
        return attrs


class AvailabilitySetSerializer(serializers.Serializer):
    timezone = serializers.CharField(max_length=64)
    rules = AvailabilityRuleInputSerializer(many=True, max_length=100)

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise serializers.ValidationError(
                "Enter a valid IANA time zone, such as Asia/Karachi."
            ) from exc
        return value

    def validate_rules(self, rules):
        by_weekday = {}
        for rule in rules:
            day_rules = by_weekday.setdefault(rule["weekday"], [])
            if any(
                rule["starts_at"] < existing["ends_at"]
                and rule["ends_at"] > existing["starts_at"]
                for existing in day_rules
            ):
                raise serializers.ValidationError(
                    "Availability rules on the same weekday cannot overlap."
                )
            day_rules.append(rule)
        return rules


class AvailabilityRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeeklyAvailabilityRule
        fields = ["weekday", "starts_at", "ends_at"]


class AvailabilityScheduleSerializer(serializers.Serializer):
    provider_id = UserIdField()
    timezone = serializers.CharField(allow_null=True)
    rules = AvailabilityRuleSerializer(many=True)


class SlotQuerySerializer(serializers.Serializer):
    provider_id = UserIdField()
    date = serializers.DateField()
    duration_minutes = serializers.IntegerField(
        required=False, default=30, min_value=15, max_value=240
    )

    def validate_duration_minutes(self, value):
        if value % 15:
            raise serializers.ValidationError("Duration must be a multiple of 15 minutes.")
        return value
