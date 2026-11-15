from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    """
    Custom manager for User model where email is the unique identifier
    for authentication instead of a username.
    """

    def create_user(self, email, full_name, profession, password=None, **extra_fields):
        """
        Create and return a regular user with the given email, full name,
        profession, and password.
        """
        if not email:
            raise ValueError('Users must have an email address.')
        if not full_name:
            raise ValueError('Users must have a full name.')
        if not profession:
            raise ValueError('Users must have a profession.')

        email = self.normalize_email(email).lower()
        user = self.model(
            email=email,
            full_name=full_name,
            profession=profession,
            **extra_fields,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, profession, password=None, **extra_fields):
        """
        Create and return a superuser with the given email, full name,
        profession, and password.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, full_name, profession, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model for the Appointly authentication service.

    Uses email as the unique login identifier instead of a username.
    """

    id = models.BigAutoField(primary_key=True)
    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    profession = models.CharField(max_length=100)
    google_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text="Google's verified subject identifier (sub claim) for Google Sign-In users.",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name', 'profession']

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']

    def __str__(self):
        return self.email
