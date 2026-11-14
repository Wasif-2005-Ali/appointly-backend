import os

os.environ.setdefault(
    "SECRET_KEY",
    "appointly-test-secret-key-not-for-real-token-usage-32bytes",
)
os.environ.setdefault("POSTGRES_DB", "appointly_test")
os.environ.setdefault("POSTGRES_USER", "appointly_test")
os.environ.setdefault("POSTGRES_PASSWORD", "appointly_test")

from .settings import *  # noqa: F403

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
