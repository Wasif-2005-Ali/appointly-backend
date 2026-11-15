"""
Tests for the Google ID token verification service and input serializer.

All tests mock ``google.oauth2.id_token.verify_oauth2_token`` so that no
real network calls or genuine Google credentials are used.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from authentication.google_auth import GoogleAuthError, verify_google_id_token
from authentication.google_serializers import GoogleAuthSerializer


# ======================================================================
# Helper fixtures
# ======================================================================

FAKE_CLIENT_ID = 'test-client-id-000.apps.googleusercontent.com'

VALID_GOOGLE_CLAIMS = {
    'iss': 'accounts.google.com',
    'sub': '1234567890',
    'email': 'testuser@gmail.com',
    'email_verified': True,
    'name': 'Test User',
    'aud': FAKE_CLIENT_ID,
}

_VERIFY_PATH = 'authentication.google_auth.id_token.verify_oauth2_token'


# ======================================================================
# verify_google_id_token – Valid token
# ======================================================================

@override_settings(GOOGLE_CLIENT_ID=FAKE_CLIENT_ID)
class VerifyGoogleIdTokenValidTest(SimpleTestCase):
    """Happy-path: a well-formed, valid Google ID token."""

    @patch(_VERIFY_PATH)
    def test_returns_correct_claims(self, mock_verify):
        mock_verify.return_value = VALID_GOOGLE_CLAIMS.copy()

        result = verify_google_id_token('valid-token-string')

        self.assertEqual(result['google_id'], '1234567890')
        self.assertEqual(result['email'], 'testuser@gmail.com')
        self.assertEqual(result['full_name'], 'Test User')

    @patch(_VERIFY_PATH)
    def test_accepts_https_issuer(self, mock_verify):
        claims = {**VALID_GOOGLE_CLAIMS, 'iss': 'https://accounts.google.com'}
        mock_verify.return_value = claims

        result = verify_google_id_token('valid-token-string')

        self.assertEqual(result['google_id'], '1234567890')

    @patch(_VERIFY_PATH)
    def test_missing_name_defaults_to_empty_string(self, mock_verify):
        claims = VALID_GOOGLE_CLAIMS.copy()
        del claims['name']
        mock_verify.return_value = claims

        result = verify_google_id_token('valid-token-string')

        self.assertEqual(result['full_name'], '')

    @patch(_VERIFY_PATH)
    def test_passes_audience_and_request_to_library(self, mock_verify):
        mock_verify.return_value = VALID_GOOGLE_CLAIMS.copy()

        verify_google_id_token('some-token')

        mock_verify.assert_called_once()
        call_args = mock_verify.call_args
        self.assertEqual(call_args[0][0], 'some-token')
        self.assertEqual(call_args[1].get('audience') or call_args[0][2], FAKE_CLIENT_ID)


# ======================================================================
# verify_google_id_token – Invalid signature / expired / wrong audience
# ======================================================================

@override_settings(GOOGLE_CLIENT_ID=FAKE_CLIENT_ID)
class VerifyGoogleIdTokenInvalidSignatureTest(SimpleTestCase):
    """Token with an invalid cryptographic signature."""

    @patch(_VERIFY_PATH, side_effect=ValueError('Invalid token'))
    def test_raises_google_auth_error(self, _mock):
        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('bad-signature-token')

        self.assertIn('Invalid Google ID token', ctx.exception.detail)


@override_settings(GOOGLE_CLIENT_ID=FAKE_CLIENT_ID)
class VerifyGoogleIdTokenExpiredTest(SimpleTestCase):
    """Token that has expired (google-auth raises ValueError)."""

    @patch(_VERIFY_PATH, side_effect=ValueError('Token expired'))
    def test_raises_google_auth_error(self, _mock):
        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('expired-token')

        self.assertIn('Invalid Google ID token', ctx.exception.detail)


@override_settings(GOOGLE_CLIENT_ID=FAKE_CLIENT_ID)
class VerifyGoogleIdTokenWrongAudienceTest(SimpleTestCase):
    """Token whose audience does not match GOOGLE_CLIENT_ID."""

    @patch(_VERIFY_PATH, side_effect=ValueError('Wrong audience'))
    def test_raises_google_auth_error(self, _mock):
        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('wrong-audience-token')

        self.assertIn('Invalid Google ID token', ctx.exception.detail)


# ======================================================================
# verify_google_id_token – Invalid issuer
# ======================================================================

@override_settings(GOOGLE_CLIENT_ID=FAKE_CLIENT_ID)
class VerifyGoogleIdTokenInvalidIssuerTest(SimpleTestCase):
    """Token with an issuer that is not accounts.google.com."""

    @patch(_VERIFY_PATH)
    def test_unknown_issuer_raises_error(self, mock_verify):
        claims = {**VALID_GOOGLE_CLAIMS, 'iss': 'https://evil.example.com'}
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('token-with-bad-issuer')

        self.assertIn('Invalid Google ID token', ctx.exception.detail)

    @patch(_VERIFY_PATH)
    def test_empty_issuer_raises_error(self, mock_verify):
        claims = {**VALID_GOOGLE_CLAIMS, 'iss': ''}
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError):
            verify_google_id_token('token-with-empty-issuer')

    @patch(_VERIFY_PATH)
    def test_missing_issuer_raises_error(self, mock_verify):
        claims = VALID_GOOGLE_CLAIMS.copy()
        del claims['iss']
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError):
            verify_google_id_token('token-without-issuer')


# ======================================================================
# verify_google_id_token – Unverified email
# ======================================================================

@override_settings(GOOGLE_CLIENT_ID=FAKE_CLIENT_ID)
class VerifyGoogleIdTokenUnverifiedEmailTest(SimpleTestCase):
    """Token with email_verified set to False or missing."""

    @patch(_VERIFY_PATH)
    def test_email_verified_false_raises_error(self, mock_verify):
        claims = {**VALID_GOOGLE_CLAIMS, 'email_verified': False}
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('unverified-email-token')

        self.assertIn('not verified', ctx.exception.detail)

    @patch(_VERIFY_PATH)
    def test_email_verified_missing_raises_error(self, mock_verify):
        claims = VALID_GOOGLE_CLAIMS.copy()
        del claims['email_verified']
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('no-email-verified-token')

        self.assertIn('not verified', ctx.exception.detail)

    @patch(_VERIFY_PATH)
    def test_email_verified_as_string_true_raises_error(self, mock_verify):
        """The string 'true' is not boolean True – must be rejected."""
        claims = {**VALID_GOOGLE_CLAIMS, 'email_verified': 'true'}
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError):
            verify_google_id_token('string-email-verified-token')


# ======================================================================
# verify_google_id_token – Missing claims
# ======================================================================

@override_settings(GOOGLE_CLIENT_ID=FAKE_CLIENT_ID)
class VerifyGoogleIdTokenMissingClaimsTest(SimpleTestCase):
    """Tokens that are missing required ``sub`` or ``email`` claims."""

    @patch(_VERIFY_PATH)
    def test_missing_sub_raises_error(self, mock_verify):
        claims = VALID_GOOGLE_CLAIMS.copy()
        del claims['sub']
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('no-sub-token')

        self.assertIn('Invalid Google ID token', ctx.exception.detail)

    @patch(_VERIFY_PATH)
    def test_empty_sub_raises_error(self, mock_verify):
        claims = {**VALID_GOOGLE_CLAIMS, 'sub': ''}
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError):
            verify_google_id_token('empty-sub-token')

    @patch(_VERIFY_PATH)
    def test_whitespace_sub_raises_error(self, mock_verify):
        claims = {**VALID_GOOGLE_CLAIMS, 'sub': '   '}
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError):
            verify_google_id_token('whitespace-sub-token')

    @patch(_VERIFY_PATH)
    def test_missing_email_raises_error(self, mock_verify):
        claims = VALID_GOOGLE_CLAIMS.copy()
        del claims['email']
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError):
            verify_google_id_token('no-email-token')

    @patch(_VERIFY_PATH)
    def test_empty_email_raises_error(self, mock_verify):
        claims = {**VALID_GOOGLE_CLAIMS, 'email': ''}
        mock_verify.return_value = claims

        with self.assertRaises(GoogleAuthError):
            verify_google_id_token('empty-email-token')


# ======================================================================
# verify_google_id_token – Missing GOOGLE_CLIENT_ID configuration
# ======================================================================

@override_settings(GOOGLE_CLIENT_ID=None)
class VerifyGoogleIdTokenMissingConfigNoneTest(SimpleTestCase):
    """GOOGLE_CLIENT_ID is None – server misconfiguration."""

    def test_raises_google_auth_error(self):
        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('any-token')

        self.assertIn('not available', ctx.exception.detail)


@override_settings(GOOGLE_CLIENT_ID='')
class VerifyGoogleIdTokenMissingConfigEmptyTest(SimpleTestCase):
    """GOOGLE_CLIENT_ID is an empty string – server misconfiguration."""

    def test_raises_google_auth_error(self):
        with self.assertRaises(GoogleAuthError) as ctx:
            verify_google_id_token('any-token')

        self.assertIn('not available', ctx.exception.detail)


# ======================================================================
# GoogleAuthSerializer – id_token validation
# ======================================================================

class GoogleAuthSerializerIdTokenTest(SimpleTestCase):
    """Validate the ``id_token`` field on the input serializer."""

    def test_valid_id_token(self):
        serializer = GoogleAuthSerializer(data={'id_token': 'abc123'})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['id_token'], 'abc123')

    def test_missing_id_token_is_invalid(self):
        serializer = GoogleAuthSerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn('id_token', serializer.errors)

    def test_empty_id_token_is_invalid(self):
        serializer = GoogleAuthSerializer(data={'id_token': ''})
        self.assertFalse(serializer.is_valid())
        self.assertIn('id_token', serializer.errors)

    def test_blank_id_token_is_invalid(self):
        serializer = GoogleAuthSerializer(data={'id_token': '   '})
        self.assertFalse(serializer.is_valid())
        self.assertIn('id_token', serializer.errors)

    def test_id_token_is_trimmed(self):
        serializer = GoogleAuthSerializer(data={'id_token': '  token123  '})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['id_token'], 'token123')


# ======================================================================
# GoogleAuthSerializer – profession field
# ======================================================================

class GoogleAuthSerializerProfessionTest(SimpleTestCase):
    """Validate the optional ``profession`` field."""

    def test_profession_is_optional(self):
        serializer = GoogleAuthSerializer(data={'id_token': 'abc123'})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('profession', serializer.validated_data)

    def test_valid_profession(self):
        serializer = GoogleAuthSerializer(
            data={'id_token': 'abc123', 'profession': 'Doctor'}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['profession'], 'Doctor')

    def test_profession_max_length(self):
        long_profession = 'x' * 101
        serializer = GoogleAuthSerializer(
            data={'id_token': 'abc123', 'profession': long_profession}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('profession', serializer.errors)

    def test_profession_at_max_length_is_valid(self):
        profession_100 = 'x' * 100
        serializer = GoogleAuthSerializer(
            data={'id_token': 'abc123', 'profession': profession_100}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_blank_profession_is_invalid(self):
        serializer = GoogleAuthSerializer(
            data={'id_token': 'abc123', 'profession': ''}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('profession', serializer.errors)

    def test_profession_is_trimmed(self):
        serializer = GoogleAuthSerializer(
            data={'id_token': 'abc123', 'profession': '  Engineer  '}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['profession'], 'Engineer')
