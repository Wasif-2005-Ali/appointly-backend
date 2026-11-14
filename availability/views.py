from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.locks import lock_users
from .models import WeeklyAvailability, WeeklyAvailabilityRule
from .serializers import (
    AvailabilityScheduleSerializer,
    AvailabilitySetSerializer,
    SlotQuerySerializer,
)
from .services import get_available_slots


class MyAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        schedule = (
            WeeklyAvailability.objects.prefetch_related("rules")
            .filter(provider_id=str(request.user.pk))
            .first()
        )
        if schedule is None:
            data = {
                "provider_id": str(request.user.pk),
                "timezone": None,
                "rules": [],
            }
        else:
            data = {
                "provider_id": schedule.provider_id,
                "timezone": schedule.timezone,
                "rules": [
                    {
                        "weekday": rule.weekday,
                        "starts_at": rule.starts_at.strftime("%H:%M"),
                        "ends_at": rule.ends_at.strftime("%H:%M"),
                    }
                    for rule in schedule.rules.all()
                ],
            }
        return Response(AvailabilityScheduleSerializer(data).data)

    def put(self, request):
        serializer = AvailabilitySetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        provider_id = str(request.user.pk)

        with transaction.atomic():
            lock_users([provider_id])
            schedule, _ = WeeklyAvailability.objects.update_or_create(
                provider_id=provider_id,
                defaults={"timezone": values["timezone"]},
            )
            schedule.rules.all().delete()
            WeeklyAvailabilityRule.objects.bulk_create(
                [
                    WeeklyAvailabilityRule(schedule=schedule, **rule)
                    for rule in values["rules"]
                ]
            )

        data = {
            "provider_id": schedule.provider_id,
            "timezone": schedule.timezone,
            "rules": [
                {
                    "weekday": rule["weekday"],
                    "starts_at": rule["starts_at"].strftime("%H:%M"),
                    "ends_at": rule["ends_at"].strftime("%H:%M"),
                }
                for rule in values["rules"]
            ],
        }
        return Response(data, status=status.HTTP_200_OK)


class AvailabilitySlotsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        serializer = SlotQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        slots = get_available_slots(
            provider_id=values["provider_id"],
            day=values["date"],
            duration_minutes=values["duration_minutes"],
        )
        return Response(
            {
                "provider_id": values["provider_id"],
                "date": values["date"].isoformat(),
                "duration_minutes": values["duration_minutes"],
                "slots": slots,
            }
        )
