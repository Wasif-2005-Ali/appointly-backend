"""Tests for the polish features: user search, profile update (PATCH /me/),
and the hosted password-reset web page."""

from urllib.parse import urlsplit

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import override_settings
from django.test import TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


def _make_user(email, full_name, profession="Student",
               password="SecurePass123!"):
    return User.objects.create_user(
        email=email,
        full_name=full_name,
        profession=profession,
        password=password,
    )


class UserSearchTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.me = _make_user(
            "me@example.com", "Me Test User", "Student",
        )
        self.alice = _make_user(
            "alice.anderson@example.com", "Alice Anderson", "Doctor",
        )
        self.bob = _make_user(
            "bob.builder@example.com", "Bob Builder", "Engineer",
        )

        access = str(RefreshToken.for_user(self.me).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        self.search_url = "/api/v1/auth/users/"

    def _search(self, query=None):
        url = self.search_url
        if query is not None:
            url = f"{url}?search={query}"
        return self.client.get(url)

    def test_search_matches_full_name(self):
        response = self._search("alice")

        self.assertEqual(response.status_code, 200)
        emails = [user["email"] for user in response.data]
        self.assertEqual(emails, ["alice.anderson@example.com"])

    def test_search_matches_email(self):
        response = self._search("bob.builder")

        self.assertEqual(response.status_code, 200)
        emails = [user["email"] for user in response.data]
        self.assertEqual(emails, ["bob.builder@example.com"])

    def test_search_is_case_insensitive(self):
        response = self._search("ALICE")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["email"], "alice.anderson@example.com")

    def test_search_excludes_requesting_user(self):
        response = self._search("Me Test User")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_search_requires_auth(self):
        self.client.credentials()  # clear the token

        response = self._search("alice")

        self.assertEqual(response.status_code, 401)

    def test_missing_search_param_returns_empty_list(self):
        response = self._search()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_empty_search_param_returns_empty_list(self):
        response = self._search("")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_search_result_shape(self):
        response = self._search("alice")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            set(response.data[0].keys()),
            {"id", "full_name", "email", "profession"},
        )
        self.assertEqual(response.data[0]["id"], self.alice.id)
        self.assertEqual(response.data[0]["full_name"], "Alice Anderson")
        self.assertEqual(response.data[0]["profession"], "Doctor")

    def test_search_returns_at_most_20_results(self):
        for i in range(25):
            _make_user(
                f"testuser{i:02d}@example.com",
                f"Testuser Number {i:02d}",
            )

        response = self._search("testuser")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 20)


class ProfileUpdateTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user = _make_user(
            "profile@example.com", "Original Name", "Student",
            password="OriginalPass!4829",
        )

        access = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        self.me_url = "/api/v1/auth/me/"

    def test_patch_updates_full_name_and_profession(self):
        response = self.client.patch(
            self.me_url,
            {"full_name": "Updated Name", "profession": "Doctor"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        # Same shape as GET /me/.
        self.assertEqual(response.data["id"], self.user.id)
        self.assertEqual(response.data["full_name"], "Updated Name")
        self.assertEqual(response.data["email"], "profile@example.com")
        self.assertEqual(response.data["profession"], "Doctor")

        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Updated Name")
        self.assertEqual(self.user.profession, "Doctor")

    def test_patch_partial_update_leaves_other_fields_unchanged(self):
        response = self.client.patch(
            self.me_url,
            {"profession": "Engineer"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["full_name"], "Original Name")
        self.assertEqual(response.data["profession"], "Engineer")

    def test_patch_cannot_change_email(self):
        response = self.client.patch(
            self.me_url,
            {"email": "newemail@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "profile@example.com")

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "profile@example.com")

    def test_patch_cannot_change_password(self):
        response = self.client.patch(
            self.me_url,
            {"password": "HackedPass!9999"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OriginalPass!4829"))
        self.assertFalse(self.user.check_password("HackedPass!9999"))

    def test_patch_requires_auth(self):
        self.client.credentials()  # clear the token

        response = self.client.patch(
            self.me_url,
            {"full_name": "Nope"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    def test_patch_rejects_blank_full_name(self):
        response = self.client.patch(
            self.me_url,
            {"full_name": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Original Name")


@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
        }
    }
)
class PasswordResetPageTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user = _make_user(
            "page.reset@example.com", "Page Reset", "Student",
            password="OldSecurePass!2026",
        )
        mail.outbox.clear()

    def _reset_url(self, user=None, token=None):
        user = user or self.user
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = token or default_token_generator.make_token(user)
        return f"/reset-password/{uid}/{token}/"

    def test_reset_page_loads_with_valid_link(self):
        response = self.client.get(self._reset_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reset your password")
        self.assertContains(response, 'name="new_password"')
        self.assertContains(response, 'name="confirm_password"')

    def test_reset_page_completes_reset(self):
        response = self.client.post(
            self._reset_url(),
            {
                "new_password": "NewSecurePass!2026",
                "confirm_password": "NewSecurePass!2026",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password reset successfully")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSecurePass!2026"))
        self.assertFalse(self.user.check_password("OldSecurePass!2026"))

    def test_reset_page_rejects_invalid_token(self):
        response = self.client.get(self._reset_url(token="invalid-token"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid or has expired")

    def test_reset_page_rejects_mismatched_passwords(self):
        response = self.client.post(
            self._reset_url(),
            {
                "new_password": "NewSecurePass!2026",
                "confirm_password": "DifferentSecurePass!2026",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldSecurePass!2026"))

    def test_reset_email_links_to_hosted_page_not_localhost(self):
        response = self.client.post(
            "/api/v1/auth/password-reset/",
            {"email": self.user.email},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        body = mail.outbox[0].body
        self.assertNotIn("localhost:3000", body)
        self.assertIn(
            "https://appointly-backend-dogk.onrender.com/reset-password/",
            body,
        )

    def test_reset_link_from_email_works_end_to_end(self):
        self.client.post(
            "/api/v1/auth/password-reset/",
            {"email": self.user.email},
            format="json",
        )

        reset_url = next(
            line
            for line in mail.outbox[0].body.splitlines()
            if "/reset-password/" in line
        )
        path = urlsplit(reset_url).path

        get_response = self.client.get(path)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Reset your password")

        post_response = self.client.post(
            path,
            {
                "new_password": "EmailFlowPass!2026",
                "confirm_password": "EmailFlowPass!2026",
            },
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Password reset successfully")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("EmailFlowPass!2026"))
