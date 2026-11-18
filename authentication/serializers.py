from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from django.contrib.auth import password_validation

from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration.

    Accepts full_name, email, profession, password, and confirm_password.
    Validates that both passwords match, enforces Django's password strength
    rules, checks email uniqueness, and creates the user with a hashed
    password via User.objects.create_user().
    """

    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )
    confirm_password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )

    class Meta:
        model = User
        fields = [
            'id',
            'full_name',
            'email',
            'profession',
            'password',
            'confirm_password',
        ]
        read_only_fields = ['id']
        # DRF auto-generates a UniqueValidator for the unique email
        # field, and it fires BEFORE validate_email() — so the
        # friendly message in validate_email() never surfaced; clients
        # saw DRF's default "user with this email already exists."
        # instead. Declaring the validator here replaces the generated
        # one (extra_kwargs wins) with the same friendly message.
        extra_kwargs = {
            'email': {
                'validators': [
                    UniqueValidator(
                        queryset=User.objects.all(),
                        message='A user with this email already exists.',
                    ),
                ],
            },
        }

    # ------------------------------------------------------------------
    # Field-level validation
    # ------------------------------------------------------------------

    def validate_email(self, value):
        """Reject duplicate emails (case-insensitive)."""
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                'A user with this email already exists.'
            )
        return value

    # ------------------------------------------------------------------
    # Object-level validation
    # ------------------------------------------------------------------

    def validate(self, attrs):
        """
        1. Ensure password and confirm_password match.
        2. Run Django's AUTH_PASSWORD_VALIDATORS against the password.
        """
        password = attrs.get('password')
        confirm_password = attrs.get('confirm_password')

        if password != confirm_password:
            raise serializers.ValidationError(
                {'confirm_password': 'Passwords do not match.'}
            )

        # Build a temporary user instance so validators that check
        # similarity to user attributes (e.g. UserAttributeSimilarityValidator)
        # can work correctly.
        user = User(
            email=attrs.get('email'),
            full_name=attrs.get('full_name'),
        )
        password_validation.validate_password(password=password, user=user)

        return attrs

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def create(self, validated_data):
        """
        Remove confirm_password from the validated data and delegate
        user creation to the custom manager so set_password() is called.
        """
        validated_data.pop('confirm_password')

        user = User.objects.create_user(
            email=validated_data['email'],
            full_name=validated_data['full_name'],
            profession=validated_data['profession'],
            password=validated_data['password'],
        )
        return user


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for partial profile updates (PATCH /me/).

    Only full_name and profession may be changed. Email and password
    are not fields here, so they can never be changed through this
    endpoint (any such keys in the request body are ignored).
    """

    class Meta:
        model = User
        fields = ['full_name', 'profession']
        extra_kwargs = {
            'full_name': {'required': False},
            'profession': {'required': False},
        }
