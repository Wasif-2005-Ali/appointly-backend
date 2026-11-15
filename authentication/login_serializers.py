
from django.contrib.auth import get_user_model
from rest_framework import serializers


User = get_user_model()


class LoginSerializer(serializers.Serializer):
    """
    Authenticate users using email and password.
    Email comparison is case-insensitive.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        password = attrs.get('password')

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {'detail': 'Invalid email or password.'}
            )

        if not user.is_active or not user.check_password(password):
            raise serializers.ValidationError(
                {'detail': 'Invalid email or password.'}
            )

        self.user = user
        return attrs
