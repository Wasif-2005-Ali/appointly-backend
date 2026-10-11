"""
call/db.py — MongoDB connection singleton for the call app.

Uses the same MongoClient pool as the chat app (same MONGODB_URI /
MONGODB_NAME) but accesses call-specific collections.
"""

from __future__ import annotations

from functools import lru_cache

import pymongo
from django.conf import settings


@lru_cache(maxsize=1)
def _get_client() -> pymongo.MongoClient:
    """Shared MongoClient — one instance per process."""
    return pymongo.MongoClient(settings.MONGODB_URI)


def get_db() -> pymongo.database.Database:
    return _get_client()[settings.MONGODB_NAME]


def get_sessions_collection() -> pymongo.collection.Collection:
    """``call_sessions`` — one document per call attempt."""
    return get_db()["call_sessions"]


def ensure_indexes() -> None:
    """
    Create indexes for the call_sessions collection.
    Call this once at startup (e.g. from AppConfig.ready).
    """
    col = get_sessions_collection()
    col.create_index("call_id",   unique=True)
    col.create_index("caller_id")
    col.create_index("callee_id")
    col.create_index("status")
    col.create_index("started_at")
