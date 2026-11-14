from django.urls import path

from .views import AvailabilitySlotsView, MyAvailabilityView


urlpatterns = [
    path("me/", MyAvailabilityView.as_view(), name="my-availability"),
    path("slots/", AvailabilitySlotsView.as_view(), name="availability-slots"),
]
