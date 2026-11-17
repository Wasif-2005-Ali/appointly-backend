from django.urls import path

from .views import AppointmentActionView, AppointmentDetailView, AppointmentListCreateView


urlpatterns = [
    path("", AppointmentListCreateView.as_view(), name="appointment-list-create"),
    path(
        "<int:appointment_id>/",
        AppointmentDetailView.as_view(),
        name="appointment-detail",
    ),
    path(
        "<int:appointment_id>/accept/",
        AppointmentActionView.as_view(),
        {"action": "accept"},
        name="appointment-accept",
    ),
    path(
        "<int:appointment_id>/reject/",
        AppointmentActionView.as_view(),
        {"action": "reject"},
        name="appointment-reject",
    ),
    path(
        "<int:appointment_id>/cancel/",
        AppointmentActionView.as_view(),
        {"action": "cancel"},
        name="appointment-cancel",
    ),
    path(
        "<int:appointment_id>/complete/",
        AppointmentActionView.as_view(),
        {"action": "complete"},
        name="appointment-complete",
    ),
    path(
        "<int:appointment_id>/reschedule/",
        AppointmentActionView.as_view(),
        name="appointment-reschedule",
    ),
]
