"""Custom password hashers for Appointly."""

from django.contrib.auth.hashers import PBKDF2PasswordHasher


class PBKDF2PasswordHasher600k(PBKDF2PasswordHasher):
    """
    PBKDF2-HMAC-SHA256 at 600,000 iterations.

    Django 6.1's default PBKDF2 hasher runs 1,500,000 iterations, which
    costs ~4.5s per login on Render's free CPU. 600,000 is the OWASP
    minimum for PBKDF2-HMAC-SHA256. The algorithm name stays
    ``pbkdf2_sha256``, and the iteration count is stored in each hash,
    so existing hashes keep verifying (Django re-hashes them at the
    new count on the next successful login).
    """

    iterations = 600_000
