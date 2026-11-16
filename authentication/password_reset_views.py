from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.html import escape
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views import View

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .password_reset_serializers import (
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        user = User.objects.filter(
            email__iexact=email,
            is_active=True,
        ).first()

        if user and user.has_usable_password():
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)

            # Link to the hosted reset page (e.g.
            # https://appointly-backend-dogk.onrender.com/reset-password/<uid>/<token>/).
            # The base URL comes from SITE_URL so it never points at a
            # local dev address.
            reset_path = reverse(
                "password_reset_page",
                kwargs={"uidb64": uid, "token": token},
            )
            base_url = settings.SITE_URL.rstrip("/")
            reset_link = f"{base_url}{reset_path}"

            message = (
                f"Hello {user.full_name},\n\n"
                "We received a request to reset your Appointly password.\n"
                "Use the link below:\n\n"
                f"{reset_link}\n\n"
                "If you did not request this, ignore this email."
            )

            send_mail(
                subject="Appointly Password Reset",
                message=message,
                from_email=None,
                recipient_list=[user.email],
                fail_silently=False,
            )

        return Response(
            {
                "message": (
                    "If an account exists with this email, "
                    "password reset instructions have been sent."
                )
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        uid_value = request.data.get("uid", "")
        token = request.data.get("token", "")

        try:
            user_id = force_str(urlsafe_base64_decode(uid_value))
            user = User.objects.get(pk=user_id, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            return Response(
                {"detail": "Invalid or expired reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Invalid or expired reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PasswordResetConfirmSerializer(
            data=request.data,
            context={"user": user},
        )
        serializer.is_valid(raise_exception=True)

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        return Response(
            {"message": "Password has been reset successfully."},
            status=status.HTTP_200_OK,
        )


# ------------------------------------------------------------------
# Hosted password-reset web page (opened from the link in the email)
# ------------------------------------------------------------------

def _get_reset_user(uidb64, token):
    """Return the user for a valid uid/token pair, else None."""
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=user_id, is_active=True)
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        return None

    if not default_token_generator.check_token(user, token):
        return None

    return user


_PAGE_STYLE = """
    * { box-sizing: border-box; }
    body {
        margin: 0;
        font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background: #f4f6f8;
        color: #1f2933;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        padding: 16px;
    }
    .card {
        background: #ffffff;
        border-radius: 12px;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
        max-width: 420px;
        width: 100%;
        padding: 32px 28px;
        text-align: center;
    }
    h1 { font-size: 22px; margin: 0 0 8px; }
    p { font-size: 14px; line-height: 1.5; color: #52606d; margin: 0 0 20px; }
    .logo { font-size: 26px; font-weight: 700; color: #2563eb; margin-bottom: 16px; }
    label { display: block; text-align: left; font-size: 13px; font-weight: 600; margin: 12px 0 4px; }
    input[type="password"] {
        width: 100%;
        padding: 11px 12px;
        font-size: 15px;
        border: 1px solid #cbd2d9;
        border-radius: 8px;
    }
    input[type="password"]:focus { outline: none; border-color: #2563eb; }
    button {
        width: 100%;
        margin-top: 20px;
        padding: 12px;
        font-size: 15px;
        font-weight: 600;
        color: #ffffff;
        background: #2563eb;
        border: none;
        border-radius: 8px;
        cursor: pointer;
    }
    button:hover { background: #1d4ed8; }
    .error {
        background: #fef2f2;
        color: #b91c1c;
        border: 1px solid #fecaca;
        border-radius: 8px;
        padding: 10px 12px;
        font-size: 13px;
        text-align: left;
        margin-bottom: 8px;
    }
    .success-icon { font-size: 44px; margin-bottom: 12px; }
"""


def _render_page(title, body_html):
    """Wrap *body_html* in the shared page shell."""
    return HttpResponse(
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title} — Appointly</title>\n"
        f"<style>{_PAGE_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        "<div class=\"card\">\n"
        "<div class=\"logo\">Appointly</div>\n"
        f"{body_html}\n"
        "</div>\n"
        "</body>\n"
        "</html>"
    )


def _flatten_errors(errors):
    """Turn DRF serializer errors into a single readable message."""
    messages = []
    for field, field_errors in errors.items():
        for message in field_errors:
            messages.append(str(message))
    return " ".join(messages) if messages else "Please check your input."


class PasswordResetPageView(View):
    """GET/POST /reset-password/<uidb64>/<token>/ — reset via a web page.

    Serves the form the reset email links to. On submit it reuses the
    same validation as the API confirm endpoint (password match +
    Django password strength rules) and shows a success page.
    """

    def _invalid_link_response(self):
        return _render_page(
            "Invalid link",
            "<h1>This reset link is invalid or has expired.</h1>"
            "<p>Please request a new password reset from the Appointly app.</p>",
        )

    def _form_response(self, request, error=None):
        error_html = (
            f'<div class="error">{escape(error)}</div>' if error else ""
        )
        csrf_token = get_token(request)
        return _render_page(
            "Reset your password",
            "<h1>Reset your password</h1>"
            "<p>Choose a new password for your Appointly account.</p>"
            f"{error_html}"
            '<form method="post">'
            f'<input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">'
            '<label for="new_password">New password</label>'
            '<input type="password" id="new_password" name="new_password" '
            'autocomplete="new-password" required>'
            '<label for="confirm_password">Confirm new password</label>'
            '<input type="password" id="confirm_password" name="confirm_password" '
            'autocomplete="new-password" required>'
            '<button type="submit">Reset password</button>'
            "</form>",
        )

    def get(self, request, uidb64, token):
        if _get_reset_user(uidb64, token) is None:
            return self._invalid_link_response()
        return self._form_response(request)

    def post(self, request, uidb64, token):
        user = _get_reset_user(uidb64, token)
        if user is None:
            return self._invalid_link_response()

        serializer = PasswordResetConfirmSerializer(
            data={
                "uid": uidb64,
                "token": token,
                "new_password": request.POST.get("new_password", ""),
                "confirm_password": request.POST.get("confirm_password", ""),
            },
            context={"user": user},
        )

        if not serializer.is_valid():
            return self._form_response(
                request,
                error=_flatten_errors(serializer.errors),
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        return _render_page(
            "Password reset",
            '<div class="success-icon">\u2705</div>'
            "<h1>Password reset successfully</h1>"
            "<p>You can now sign in to the Appointly app with your new password.</p>",
        )
