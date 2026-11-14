import hashlib

from django.db import connection


def lock_users(user_ids):
    if connection.vendor != "postgresql":
        return

    keys = set()
    for user_id in user_ids:
        digest = hashlib.sha256(f"appointly:user:{user_id}".encode("utf-8")).digest()
        keys.add(int.from_bytes(digest[:8], byteorder="big", signed=True))

    with connection.cursor() as cursor:
        for key in sorted(keys):
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
