"""
Serializer for Google Sign-In input validation.

Handles the request payload for the Google Sign-In endpoint (Stage 3).
Validation of the actual Google ID token is delegated to the
``google_auth.verify_google_id_token`` service so each concern can be
tested independently.
"""

from rest_framework import serializers


class GoogleAuthSerializer(serializers.Serializer):
    """
    Validate the incoming Google Sign-In request payload.

    Fields
    ------
    id_token : str (required)
        The Google ID token received from the mobile client's Google
        Sign-In SDK. Must be a non-empty string.

    profession : str (optional)
        An optional profession value for new users. When a Google user
        signs in for the first time and no Appointly account exists yet,
        the view layer may use this value (or a fallback default) when
        creating the User record.

        Max length mirrors ``User.profession`` (100 characters).
    """

    id_token = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        help_text='Google ID token from the client-side Google Sign-In SDK.',
    )

    profession = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=100,
        trim_whitespace=True,
        help_text=(
            'Optional profession for new users. '
            'If omitted, a default value will be assigned.'
        ),
    )
