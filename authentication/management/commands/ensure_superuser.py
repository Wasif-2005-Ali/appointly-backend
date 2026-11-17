"""Ensure the Django admin superuser exists.

Render's free plan has no web shell, so this runs from the deploy
buildCommand (see render.yaml) instead of `createsuperuser`.

Reads DJANGO_SUPERUSER_EMAIL (default bestwasifali@gmail.com) and
DJANGO_SUPERUSER_PASSWORD from the environment. If the password is not
set it does nothing and exits 0, so a deploy never fails because of it.

The password is only set when the user is created or has no usable
password, so changing the admin password later in /admin/ is never
overwritten by a redeploy.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the admin superuser from env vars if needed (deploy-time)."

    def handle(self, *args, **options):
        email = os.environ.get(
            "DJANGO_SUPERUSER_EMAIL", "bestwasifali@gmail.com"
        ).strip().lower()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not password:
            self.stdout.write(
                "ensure_superuser: DJANGO_SUPERUSER_PASSWORD not set, skipping."
            )
            return
        try:
            User = get_user_model()
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "full_name": "Wasif Ali",
                    "profession": "Student",
                    "is_staff": True,
                    "is_superuser": True,
                    "is_active": True,
                },
            )
            changed = ["created"] if created else []
            for flag in ("is_staff", "is_superuser", "is_active"):
                if not getattr(user, flag):
                    setattr(user, flag, True)
                    changed.append(flag)
            # NB: a freshly created user has password='', which Django's
            # has_usable_password() still reports as usable, so check for
            # the empty value explicitly.
            if not user.password or not user.has_usable_password():
                user.set_password(password)
                changed.append("password set")
            if changed:
                user.save()
            self.stdout.write(
                "ensure_superuser: %s %s."
                % (email, "/".join(changed) or "already ok")
            )
        except Exception as exc:  # never fail the deploy over admin setup
            self.stdout.write("ensure_superuser: skipped due to error: %s" % exc)
