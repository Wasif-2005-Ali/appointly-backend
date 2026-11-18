"""
chat/db.py — MongoDB connection singleton for the chat app.

Reads MONGODB_URI and MONGODB_NAME from Django settings and returns
a lazily-initialised MongoClient.  Import `get_db()` wherever you
need a database handle; the client is created only once per process.
"""

from __future__ import annotations

from functools import lru_cache

import pymongo
from django.conf import settings


@lru_cache(maxsize=1)
def get_client() -> pymongo.MongoClient:
    """Return a cached MongoClient instance.

    ``tz_aware=True``: without it PyMongo returns naive datetimes for
    ``created_at`` etc. (same bug class as the call app's stuck-call
    crash — see call/db.py). ``from_dict()`` also normalises
    defensively.
    """
    return pymongo.MongoClient(settings.MONGODB_URI, tz_aware=True)


def get_db() -> pymongo.database.Database:
    """Return the chat MongoDB database."""
    return get_client()[settings.MONGODB_NAME]


# ---------------------------------------------------------------------------
# Convenience collection accessors
# ---------------------------------------------------------------------------

def get_rooms_collection() -> pymongo.collection.Collection:
    return get_db()["chat_rooms"]


def get_messages_collection() -> pymongo.collection.Collection:
    return get_db()["chat_messages"]
