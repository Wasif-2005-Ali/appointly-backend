"""
Endpoint tests for the Google Sign-In view (Stage 3).

All tests mock Google token verification, database queries, and JWT
creation.  They do not require a real Google token, a running PostgreSQL
instance, or a test database.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from authentication.google_auth import GoogleAuthError
from authentication.models import User
from authentication.views import GoogleAuthView


GOOGLE_URL = '/api/v1/auth/google/'

VALID_GOOGLE_DATA = {
    'google_id': 'google-sub-123',
    'email': 'googleuser@gmail.com',
    'full_name': 'Google User',
}


class GoogleAuthViewTestBase(SimpleTestCase):
    """Shared setUp for all GoogleAuthView endpoint tests."""

    def setUp(self):
        self.factory = APIRequestFactory()

        # Mock database queries via select_for_update().
        self.select_patch = patch.object(
            User.objects, 'select_for_update',
        )
        self.mock_select = self.select_patch.start()
        self.addCleanup(self.select_patch.stop)

        # Mock User.objects.create_user().
        self.create_patch = patch.object(
            User.objects, 'create_user',
        )
        self.mock_create = self.create_patch.start()
        self.addCleanup(self.create_patch.stop)

        # Mock Google token verification.
        self.verify_patch = patch(
            'authentication.views.verify_google_id_token',
            return_value=VALID_GOOGLE_DATA.copy(),
        )
        self.mock_verify = self.verify_patch.start()
        self.addCleanup(self.verify_patch.stop)

        # Avoid opening a real database transaction.
        self.atomic_patch = patch(
            'authentication.views.transaction.atomic',
            return_value=nullcontext(),
        )
        self.atomic_patch.start()
        self.addCleanup(self.atomic_patch.stop)

        # Mock SimpleJWT token generation.
        self.jwt_patch = patch(
            'authentication.views.RefreshToken.for_user',
        )
        self.mock_jwt = self.jwt_patch.start()
        self.addCleanup(self.jwt_patch.stop)

        fake_refresh = MagicMock()
        fake_refresh.access_token = 'test-access-token'
        fake_refresh.__str__ = MagicMock(return_value='test-refresh-token')
        self.mock_jwt.return_value = fake_refresh

    # -- Helpers --------------------------------------------------

    def make_user(self, **overrides):
        """Return a MagicMock that behaves like a User instance."""
        defaults = {
            'id': 1,
            'full_name': 'Google User',
            'email': 'googleuser@gmail.com',
            'profession': 'Doctor',
            'google_id': 'google-sub-123',
            'is_active': True,
        }
        defaults.update(overrides)
        user = MagicMock()
        for key, value in defaults.items():
            setattr(user, key, value)
        return user

    def set_query_results(self, *results):
        """Configure successive .filter().first() return values."""
        qs = self.mock_select.return_value
        qs.filter.return_value.first.side_effect = list(results)

    def post_google(self, data=None):
        """POST to the Google endpoint with sensible defaults."""
        payload = data if data is not None else {
            'id_token': 'fake-google-token',
            'profession': 'Doctor',
        }
        request = self.factory.post(GOOGLE_URL, data=payload, format='json')
        return GoogleAuthView.as_view()(request)


# ==================================================================
# 1. Successful first-time Google user registration
# ==================================================================

class GoogleAuthNewUserTest(GoogleAuthViewTestBase):
    """New Google user — no matching google_id or email in the database."""

    def test_new_user_is_created_with_correct_fields(self):
        user = self.make_user(profession='Doctor')
        self.set_query_results(None, None)
        self.mock_create.return_value = user

        response = self.post_google()

        self.assertEqual(response.status_code, 200)
        self.mock_create.assert_called_once_with(
            email='googleuser@gmail.com',
            full_name='Google User',
            profession='Doctor',
            password=None,
            google_id='google-sub-123',
        )

    def test_new_user_gets_unusable_password(self):
        user = self.make_user()
        self.set_query_results(None, None)
        self.mock_create.return_value = user

        self.post_google()

        user.set_unusable_password.assert_called_once()
        user.save.assert_called_once_with(update_fields=['password'])

    def test_new_user_response_format(self):
        user = self.make_user()
        self.set_query_results(None, None)
        self.mock_create.return_value = user

        response = self.post_google()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['message'], 'Google Sign-In successful.',
        )
        self.assertEqual(response.data['user']['email'], 'googleuser@gmail.com')
        self.assertEqual(response.data['user']['full_name'], 'Google User')
        self.assertEqual(response.data['user']['profession'], 'Doctor')
        self.assertIn('id', response.data['user'])

    def test_new_user_name_fallback_when_google_name_empty(self):
        """When Google provides no name, the email local-part is used."""
        self.mock_verify.return_value = {
            'google_id': 'google-sub-456',
            'email': 'noname@gmail.com',
            'full_name': '',
        }
        user = self.make_user(email='noname@gmail.com', full_name='noname')
        self.set_query_results(None, None)
        self.mock_create.return_value = user

        self.post_google()

        call_kwargs = self.mock_create.call_args
        self.assertEqual(call_kwargs[1]['full_name'], 'noname')


# ==================================================================
# 2. Successful login for existing Google-linked user
# ==================================================================

class GoogleAuthExistingUserTest(GoogleAuthViewTestBase):
    """User with matching google_id already exists and is active."""

    def test_existing_google_user_logs_in(self):
        user = self.make_user()
        self.set_query_results(user)

        response = self.post_google()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['message'], 'Google Sign-In successful.',
        )
        self.assertEqual(response.data['user']['email'], user.email)
        self.mock_create.assert_not_called()

    def test_existing_google_user_receives_jwt(self):
        user = self.make_user()
        self.set_query_results(user)

        response = self.post_google()

        self.mock_jwt.assert_called_once_with(user)
        self.assertEqual(
            response.data['tokens']['access'], 'test-access-token',
        )
        self.assertEqual(
            response.data['tokens']['refresh'], 'test-refresh-token',
        )


# ==================================================================
# 3. Missing profession for a new Google user
# ==================================================================

class GoogleAuthMissingProfessionTest(GoogleAuthViewTestBase):
    """New Google user without profession — must be rejected."""

    def test_missing_profession_returns_400(self):
        self.set_query_results(None, None)

        response = self.post_google(data={'id_token': 'fake-token'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('profession', response.data)
        self.mock_create.assert_not_called()
        self.mock_jwt.assert_not_called()


# ==================================================================
# 4. Existing email conflict — no automatic linking
# ==================================================================

class GoogleAuthEmailConflictTest(GoogleAuthViewTestBase):
    """Google email matches an existing account — must NOT auto-link."""

    def test_existing_email_returns_409(self):
        existing = self.make_user(google_id=None)
        self.set_query_results(None, existing)

        response = self.post_google()

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.data['detail'])
        self.mock_create.assert_not_called()
        self.mock_jwt.assert_not_called()

    def test_email_conflict_does_not_link_google_id(self):
        """The existing user's google_id must NOT be overwritten."""
        existing = self.make_user(google_id=None)
        self.set_query_results(None, existing)

        self.post_google()

        existing.save.assert_not_called()

    def test_email_conflict_with_different_google_id_returns_409(self):
        """Email match where user already has a different Google ID."""
        existing = self.make_user(google_id='other-google-id')
        self.set_query_results(None, existing)

        response = self.post_google()

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.data['detail'])
        self.mock_jwt.assert_not_called()


# ==================================================================
# 5. Inactive Google-linked user
# ==================================================================

class GoogleAuthInactiveUserTest(GoogleAuthViewTestBase):
    """Google user whose account has been deactivated."""

    def test_inactive_user_returns_403(self):
        user = self.make_user(is_active=False)
        self.set_query_results(user)

        response = self.post_google()

        self.assertEqual(response.status_code, 403)
        self.assertIn('inactive', response.data['detail'])
        self.mock_jwt.assert_not_called()
        self.mock_create.assert_not_called()


# ==================================================================
# 6. Invalid Google token
# ==================================================================

class GoogleAuthInvalidTokenTest(GoogleAuthViewTestBase):
    """Google ID token that fails verification."""

    def test_invalid_token_returns_401(self):
        self.mock_verify.side_effect = GoogleAuthError(
            'Invalid Google ID token.',
        )

        response = self.post_google()

        self.assertEqual(response.status_code, 401)
        self.assertIn('Invalid', response.data['detail'])
        self.mock_jwt.assert_not_called()

    def test_missing_id_token_returns_400(self):
        response = self.post_google(data={})

        self.assertEqual(response.status_code, 400)
        self.assertIn('id_token', response.data)
        self.mock_verify.assert_not_called()

    def test_empty_id_token_returns_400(self):
        response = self.post_google(data={'id_token': ''})

        self.assertEqual(response.status_code, 400)
        self.assertIn('id_token', response.data)
        self.mock_verify.assert_not_called()

    def test_google_unavailable_returns_401(self):
        """GOOGLE_CLIENT_ID not configured on server."""
        self.mock_verify.side_effect = GoogleAuthError(
            'Google Sign-In is not available.',
        )

        response = self.post_google()

        self.assertEqual(response.status_code, 401)
        self.assertIn('not available', response.data['detail'])


# ==================================================================
# 7. Concurrent creation / IntegrityError
# ==================================================================

class GoogleAuthConcurrencyTest(GoogleAuthViewTestBase):
    """Race condition where another request creates the user first."""

    def test_integrity_error_on_create_returns_409(self):
        self.set_query_results(None, None)
        self.mock_create.side_effect = IntegrityError(
            'duplicate key value violates unique constraint',
        )

        response = self.post_google()

        self.assertEqual(response.status_code, 409)
        self.assertIn('already been created', response.data['detail'])
        self.mock_jwt.assert_not_called()

    def test_integrity_error_does_not_leak_database_details(self):
        self.set_query_results(None, None)
        self.mock_create.side_effect = IntegrityError(
            'duplicate key value violates unique constraint '
            '"users_google_id_key"',
        )

        response = self.post_google()

        response_text = str(response.data)
        self.assertNotIn('unique constraint', response_text)
        self.assertNotIn('users_google_id_key', response_text)


# ==================================================================
# 8. JWT response structure
# ==================================================================

class GoogleAuthTokenResponseTest(GoogleAuthViewTestBase):
    """Verify the shape of the JWT token response."""

    def test_tokens_contain_access_and_refresh(self):
        user = self.make_user()
        self.set_query_results(user)

        response = self.post_google()

        self.assertIn('tokens', response.data)
        self.assertIn('access', response.data['tokens'])
        self.assertIn('refresh', response.data['tokens'])

    def test_response_contains_user_and_message(self):
        user = self.make_user()
        self.set_query_results(user)

        response = self.post_google()

        self.assertIn('message', response.data)
        self.assertIn('user', response.data)

    def test_user_data_has_required_fields(self):
        user = self.make_user()
        self.set_query_results(user)

        response = self.post_google()

        user_data = response.data['user']
        for field in ('id', 'full_name', 'email', 'profession'):
            self.assertIn(field, user_data)

    def test_response_matches_login_conventions(self):
        """Google Sign-In response mirrors the email/password login shape."""
        user = self.make_user()
        self.set_query_results(user)

        response = self.post_google()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data['tokens'], dict)
        self.assertIsInstance(response.data['user'], dict)
        self.assertIsInstance(response.data['message'], str)
