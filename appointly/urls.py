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

urlpatterns = [
    # Django admin
    path("admin/", admin.site.urls),

    # JWT auth
    path("api/auth/token/",         TokenObtainPairView.as_view(),  name="token-obtain"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(),     name="token-refresh"),
    path("api/auth/token/verify/",  TokenVerifyView.as_view(),      name="token-verify"),

    # Chat REST API
    path("api/chat/", include("chat.urls", namespace="chat")),

    # Call REST API
    path("api/call/", include("call.urls", namespace="call")),
]
