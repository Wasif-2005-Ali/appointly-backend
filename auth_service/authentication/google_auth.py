"""
Google ID token verification service.

Provides a reusable function to verify Google Sign-In ID tokens using the
official ``google-auth`` library. This module is intentionally decoupled from
Django REST Framework serializers and views so that it can be unit-tested
independently with mocked Google verification.
"""

import logging

from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)

# Google's accepted issuers for Sign-In ID tokens.
_VALID_ISSUERS = frozenset({
    'accounts.google.com',
    'https://accounts.google.com',
})


class GoogleAuthError(Exception):
    """
    Raised when Google ID token verification fails for any reason.

    The ``detail`` attribute carries a safe, user-facing message that can be
    returned in an API response without leaking internal state or secrets.
    """

    def __init__(self, detail='Google authentication failed.'):
        self.detail = detail
        super().__init__(detail)


def verify_google_id_token(token):
    """
    Verify a Google ID token and return the validated user claims.

    Uses ``google.oauth2.id_token.verify_oauth2_token`` to validate the
    token's signature, expiration, and audience against
    ``settings.GOOGLE_CLIENT_ID``.

    After library-level verification succeeds this function additionally
    checks that:
    * The issuer is ``accounts.google.com`` or
      ``https://accounts.google.com``.
    * The ``sub`` (subject) claim is present and non-empty.
    * The ``email`` claim is present and non-empty.
    * The ``email_verified`` claim is ``True``.

    Parameters
    ----------
    token : str
        The raw Google ID token string received from the client.

    Returns
    -------
    dict
        A dictionary with the following keys:

        * ``google_id``  – Google's unique subject identifier (``sub``).
        * ``email``      – The user's verified email address.
        * ``full_name``  – Display name (``name`` claim), or ``""`` if absent.

    Raises
    ------
    GoogleAuthError
        With a safe, user-facing ``detail`` message when verification fails.
    """

    # ------------------------------------------------------------------
    # Guard: ensure the server has a configured client ID
    # ------------------------------------------------------------------
    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', None)
    if not client_id:
        logger.error(
            'GOOGLE_CLIENT_ID is not configured. '
            'Google Sign-In cannot proceed.'
        )
        raise GoogleAuthError('Google Sign-In is not available.')

    # ------------------------------------------------------------------
    # Verify the token via the google-auth library
    # ------------------------------------------------------------------
    try:
        id_info = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=client_id,
        )
    except ValueError:
        # Covers invalid signatures, expired tokens, wrong audience, etc.
        logger.info('Google ID token verification failed.')
        raise GoogleAuthError('Invalid Google ID token.')

    # ------------------------------------------------------------------
    # Validate the issuer
    # ------------------------------------------------------------------
    issuer = id_info.get('iss', '')
    if issuer not in _VALID_ISSUERS:
        logger.info('Google ID token has an invalid issuer: %s', issuer)
        raise GoogleAuthError('Invalid Google ID token.')

    # ------------------------------------------------------------------
    # Validate required claims
    # ------------------------------------------------------------------
    sub = id_info.get('sub')
    if not sub or not str(sub).strip():
        logger.info('Google ID token is missing a valid "sub" claim.')
        raise GoogleAuthError('Invalid Google ID token.')

    email = id_info.get('email')
    if not email or not str(email).strip():
        logger.info('Google ID token is missing a valid "email" claim.')
        raise GoogleAuthError('Invalid Google ID token.')

    email_verified = id_info.get('email_verified')
    if email_verified is not True:
        logger.info(
            'Google ID token email is not verified for: %s', email
        )
        raise GoogleAuthError('Google email address is not verified.')

    # ------------------------------------------------------------------
    # Build and return the validated payload
    # ------------------------------------------------------------------
    return {
        'google_id': str(sub),
        'email': str(email),
        'full_name': str(id_info.get('name', '')),
    }
