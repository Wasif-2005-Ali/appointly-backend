
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from .views import (
    GoogleAuthView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('google/', GoogleAuthView.as_view(), name='google_login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path(
        'token/verify/',
        TokenVerifyView.as_view(),
        name='token_verify',
    ),
    path(
        'token/refresh/',
        TokenRefreshView.as_view(),
        name='token_refresh',
    ),
]
