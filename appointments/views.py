from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Appointment
from .serializers import (
    AppointmentCreateSerializer,
    AppointmentRescheduleSerializer,
    AppointmentSerializer,
)
from .services import (
    Conflict,
    create_appointment,
    reschedule_appointment,
    transition_appointment,
)


class AppointmentListCreateView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AppointmentSerializer

    def get_queryset(self):
        user_id = str(self.request.user.pk)
        queryset = Appointment.objects.filter(
            Q(requester_id=user_id) | Q(provider_id=user_id)
        )
        requested_status = self.request.query_params.get("status")
        if requested_status:
            valid_statuses = [value for value, _ in Appointment.Status.choices]
            if requested_status not in valid_statuses:
                raise serializers.ValidationError(
                    {"status": f"Choose one of: {', '.join(valid_statuses)}."}
                )
            queryset = queryset.filter(status=requested_status)
        return queryset.order_by("-starts_at", "-id")

    def get(self, request):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

    def post(self, request):
        serializer = AppointmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        appointment = create_appointment(
            requester_id=str(request.user.pk),
            provider_id=values["provider_id"],
            starts_at=values["starts_at"],
            ends_at=values["ends_at"],
            notes=values.get("notes", ""),
        )
        return Response(
            AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED
        )


class AppointmentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, appointment_id):
        appointment = get_object_or_404(
            Appointment.objects.filter(
                Q(requester_id=str(request.user.pk))
                | Q(provider_id=str(request.user.pk))
            ),
            pk=appointment_id,
        )
        return Response(AppointmentSerializer(appointment).data)

    def delete(self, request, appointment_id):
        appointment = get_object_or_404(Appointment, pk=appointment_id)
        if str(request.user.pk) not in {
            appointment.requester_id,
            appointment.provider_id,
        }:
            raise exceptions.PermissionDenied(
                "You are not a participant in this appointment."
            )
        if appointment.status == Appointment.Status.COMPLETED:
            # Completed appointments are history; deleting one would
            # destroy the record of a service that happened.
            raise Conflict("Completed appointments cannot be deleted.")
        appointment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppointmentActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, appointment_id, action):
        appointment = transition_appointment(
            appointment_id, str(request.user.pk), action
        )
        return Response(AppointmentSerializer(appointment).data)

    def patch(self, request, appointment_id):
        serializer = AppointmentRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appointment = reschedule_appointment(
            appointment_id=appointment_id,
            user_id=str(request.user.pk),
            starts_at=serializer.validated_data["starts_at"],
            ends_at=serializer.validated_data["ends_at"],
        )
        return Response(AppointmentSerializer(appointment).data)
