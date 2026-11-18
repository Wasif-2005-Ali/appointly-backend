"""
Authentication views for the Appointly authentication service.

Provides endpoints for:
- Email/password registration and login  (Stage 1)
- Google Sign-In                         (Stage 3)
- JWT-authenticated logout and profile retrieval
"""

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .google_auth import GoogleAuthError, verify_google_id_token
from .google_serializers import GoogleAuthSerializer
from .login_serializers import LoginSerializer
from .models import User
from .serializers import ProfileUpdateSerializer, RegisterSerializer


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _user_response(user):
    """Build the standard user-data dict used across all endpoints."""
    return {
        'id': user.id,
        'full_name': user.full_name,
        'email': user.email,
        'profession': user.profession,
    }


def _jwt_tokens(user):
    """Issue a SimpleJWT access / refresh token pair for *user*."""
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }


# ------------------------------------------------------------------
# Email / password endpoints (Stage 1)
# ------------------------------------------------------------------

class RegisterView(APIView):
    """POST /api/v1/auth/register/ — create a new user account."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                'message': 'User registered successfully.',
                'user': _user_response(user),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """POST /api/v1/auth/login/ — authenticate and receive JWT tokens."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.user
        return Response(
            {
                'message': 'Login successful.',
                'user': _user_response(user),
                **_jwt_tokens(user),
            },
            status=status.HTTP_200_OK,
        )


# ------------------------------------------------------------------
# Google Sign-In endpoint (Stage 3)
# ------------------------------------------------------------------

class GoogleAuthView(APIView):
    """POST /api/v1/auth/google/ — authenticate via Google Sign-In."""

    permission_classes = [AllowAny]

    def post(self, request):
        # --- Validate the incoming request payload ----------------
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # --- Verify the Google ID token ---------------------------
        try:
            google_data = verify_google_id_token(
                serializer.validated_data['id_token'],
            )
        except GoogleAuthError as exc:
            return Response(
                {'detail': exc.detail},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        google_id = google_data['google_id']
        email = google_data['email']
        full_name = google_data['full_name']
        profession = serializer.validated_data.get('profession')

        try:
            with transaction.atomic():
                # 1. Look up by verified Google subject ID.
                user = (
                    User.objects
                    .select_for_update()
                    .filter(google_id=google_id)
                    .first()
                )

                if user is not None:
                    # Existing Google-linked user.
                    if not user.is_active:
                        return Response(
                            {'detail': 'This account is inactive.'},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                    return Response(
                        {
                            'message': 'Google Sign-In successful.',
                            'user': _user_response(user),
                            **_jwt_tokens(user),
                        },
                        status=status.HTTP_200_OK,
                    )

                # 2. Check whether the verified email already belongs
                #    to an existing (non-Google-linked) account.
                email_user = (
                    User.objects
                    .select_for_update()
                    .filter(email__iexact=email)
                    .first()
                )

                if email_user is not None:
                    # Auto-link: the Google ID token is verified and
                    # Google confirms the email belongs to the signer,
                    # so link the Google ID to the existing account
                    # and sign them in.
                    if email_user.google_id not in (None, google_id):
                        # Already linked to a different Google account.
                        return Response(
                            {
                                'detail': (
                                    'This email is already linked to a '
                                    'different Google account. Please log '
                                    'in with your email and password.'
                                ),
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                    if not email_user.is_active:
                        return Response(
                            {'detail': 'This account is inactive.'},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                    email_user.google_id = google_id
                    email_user.save(update_fields=['google_id'])
                    return Response(
                        {
                            'message': 'Google Sign-In successful.',
                            'user': _user_response(email_user),
                            **_jwt_tokens(email_user),
                        },
                        status=status.HTTP_200_OK,
                    )

                # 3. New Google user — profession is required.
                if not profession:
                    return Response(
                        {
                            'profession': [
                                'This field is required for new Google users.',
                            ],
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Use the email local-part as a fallback display name
                # when Google does not provide a name claim.
                if not full_name:
                    full_name = email.split('@')[0]

                user = User.objects.create_user(
                    email=email,
                    full_name=full_name,
                    profession=profession,
                    password=None,
                    google_id=google_id,
                )
                user.set_unusable_password()
                user.save(update_fields=['password'])

        except IntegrityError:
            # A concurrent request created the same user between our
            # SELECT and INSERT.  Return a safe, non-leaking error.
            return Response(
                {
                    'detail': (
                        'This account has already been created. '
                        'Please try signing in again.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                'message': 'Google Sign-In successful.',
                'user': _user_response(user),
                **_jwt_tokens(user),
            },
            status=status.HTTP_200_OK,
        )


# ------------------------------------------------------------------
# Authenticated endpoints (Stage 1 continued)
# ------------------------------------------------------------------


class LogoutView(APIView):
    """POST /api/v1/auth/logout/ — blacklist the refresh token."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')

        if not refresh_token:
            return Response(
                {'detail': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)

            # Ensure the refresh token belongs to the authenticated user.
            token_user_id = token.get('user_id')

            if str(token_user_id) != str(request.user.pk):
                return Response(
                    {'detail': 'You cannot log out another user.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            token.blacklist()

        except TokenError:
            return Response(
                {'detail': 'Invalid or expired refresh token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {'message': 'Logout successful.'},
            status=status.HTTP_205_RESET_CONTENT,
        )


class MeView(APIView):
    """GET /api/v1/auth/me/ — retrieve the authenticated user's profile.
    PATCH /api/v1/auth/me/ — update full_name and/or profession."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            _user_response(request.user),
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            _user_response(request.user),
            status=status.HTTP_200_OK,
        )


class UserSearchView(APIView):
    """GET /api/v1/auth/users/?search=<query> — search users by name/email.

    Returns a JSON array (max 20) of {id, full_name, email, profession},
    excluding the requesting user. Matches full_name or email
    case-insensitively. An empty or missing search param returns []."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get('search', '').strip()

        if not query:
            return Response([], status=status.HTTP_200_OK)

        users = (
            User.objects
            .exclude(pk=request.user.pk)
            .filter(
                Q(full_name__icontains=query)
                | Q(email__icontains=query)
            )
            .order_by('full_name')[:20]
        )

        return Response(
            [_user_response(user) for user in users],
            status=status.HTTP_200_OK,
        )


class UserDetailView(APIView):
    """GET /api/v1/auth/users/<id>/ — look up one user by ID.

    Returns {id, full_name, email, profession}, or 404 if the user
    does not exist. Used by the app to resolve names in call history
    (instead of showing "User #id"). Any authenticated user may look
    up any other user — the fields returned are the same public
    profile fields the user search endpoint returns."""

    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {'detail': f"User with id '{user_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            _user_response(user),
            status=status.HTTP_200_OK,
        )
