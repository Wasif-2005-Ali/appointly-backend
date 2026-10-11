"""
call/urls.py — URL patterns for the call REST API.

Mounted at /api/call/ by the root URLconf (appointly/urls.py).
"""

from django.urls import path

from . import views

app_name = "call"

urlpatterns = [
    path("history/", views.CallHistoryView.as_view(), name="call-history"),
    path("<str:call_id>/", views.CallDetailView.as_view(), name="call-detail"),
]
