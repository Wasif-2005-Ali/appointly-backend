"""
URL configuration for appointly project.
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from authentication.password_reset_views import PasswordResetPageView
from appointly import views as public_views

urlpatterns = [
    # Public pages (no login required)
    path("", public_views.homepage, name="homepage"),
    path("privacy/", public_views.privacy_policy, name="privacy_policy"),

    # Django admin
    path("admin/", admin.site.urls),

    # Hosted password-reset page (linked from the reset email)
    path(
        "reset-password/<uidb64>/<token>/",
        PasswordResetPageView.as_view(),
        name="password_reset_page",
    ),

    # JWT auth
    path("api/auth/token/",         TokenObtainPairView.as_view(),  name="token-obtain"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(),     name="token-refresh"),
    path("api/auth/token/verify/",  TokenVerifyView.as_view(),      name="token-verify"),

    # Authentication API
    path("api/v1/auth/", include("authentication.urls")),

    # Chat REST API
    path("api/chat/", include("chat.urls", namespace="chat")),

    # Call REST API
    path("api/call/", include("call.urls", namespace="call")),

    # Appointment and provider availability APIs
    path("api/v1/appointments/", include("appointments.urls")),
    path("api/v1/availability/", include("availability.urls")),
]
