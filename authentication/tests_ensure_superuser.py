import os
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase


class EnsureSuperuserTests(TestCase):
    def run_command(self, env):
        out = StringIO()
        with mock.patch.dict(os.environ, env, clear=False):
            call_command("ensure_superuser", stdout=out)
        return out.getvalue()

    def test_creates_superuser_when_password_set(self):
        out = self.run_command({
            "DJANGO_SUPERUSER_EMAIL": "admin@example.com",
            "DJANGO_SUPERUSER_PASSWORD": "AdminPass123!",
        })
        user = get_user_model().objects.get(email="admin@example.com")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("AdminPass123!"))
        self.assertIn("created", out)

    def test_skips_without_password(self):
        env = dict(os.environ)
        env.pop("DJANGO_SUPERUSER_PASSWORD", None)
        out = StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            call_command("ensure_superuser", stdout=out)
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertIn("not set, skipping", out.getvalue())

    def test_does_not_overwrite_existing_password(self):
        User = get_user_model()
        User.objects.create_superuser(
            email="admin@example.com",
            full_name="Wasif Ali",
            profession="Student",
            password="OriginalPass123!",
        )
        self.run_command({
            "DJANGO_SUPERUSER_EMAIL": "admin@example.com",
            "DJANGO_SUPERUSER_PASSWORD": "NewPass123!",
        })
        user = User.objects.get(email="admin@example.com")
        self.assertTrue(user.check_password("OriginalPass123!"))

    def test_upgrades_existing_regular_user_without_touching_password(self):
        User = get_user_model()
        User.objects.create_user(
            email="admin@example.com",
            full_name="Wasif Ali",
            profession="Student",
            password="UserPass123!",
        )
        self.run_command({
            "DJANGO_SUPERUSER_EMAIL": "admin@example.com",
            "DJANGO_SUPERUSER_PASSWORD": "NewPass123!",
        })
        user = User.objects.get(email="admin@example.com")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("UserPass123!"))
