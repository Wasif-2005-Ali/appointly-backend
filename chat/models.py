"""
chat/models.py — PyMongo document classes for the chat app.

These are NOT Django ORM models (Django manages relational data in
PostgreSQL).  Instead, each class wraps a MongoDB collection and
provides typed dataclass-style construction alongside class methods
for common CRUD operations.

Collections
-----------
  chat_rooms     → ChatRoom documents
  chat_messages  → Message documents
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from .db import get_rooms_collection, get_messages_collection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


def _new_room_id() -> str:
    """Generate a short UUID-based room slug."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# ChatRoom
# ---------------------------------------------------------------------------

@dataclass
class ChatRoom:
    """
    Represents a chat room document stored in MongoDB.

    Attributes
    ----------
    room_id : str
        Short human-readable identifier used in WebSocket URLs and
        channel group names (e.g. ``"a3f9c12b0d4e"``).
    name : str
        Display name shown in the UI.
    participants : list[str]
        List of Django user IDs (str) who are members of this room.
    is_group : bool
        ``True`` for group chats; ``False`` for one-to-one DMs.
    created_at : datetime
        UTC timestamp of room creation.
    _id : Optional[ObjectId]
        MongoDB ``_id`` field; ``None`` until the document is inserted.
    """

    room_id: str = field(default_factory=_new_room_id)
    name: str = ""
    participants: list[str] = field(default_factory=list)
    is_group: bool = False
    created_at: datetime = field(default_factory=_now)
    _id: Optional[ObjectId] = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a dict suitable for MongoDB insertion."""
        d = asdict(self)
        d.pop("_id", None)          # let MongoDB assign _id on insert
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ChatRoom":
        """Reconstruct a ChatRoom from a MongoDB document."""
        return cls(
            room_id=data["room_id"],
            name=data.get("name", ""),
            participants=data.get("participants", []),
            is_group=data.get("is_group", False),
            created_at=data.get("created_at", _now()),
            _id=data.get("_id"),
        )

    # ------------------------------------------------------------------
    # Class-level DB operations
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        name: str,
        participants: list[str],
        *,
        is_group: bool = False,
    ) -> "ChatRoom":
        """Insert a new room document and return the populated instance."""
        room = cls(name=name, participants=participants, is_group=is_group)
        col = get_rooms_collection()
        result = col.insert_one(room.to_dict())
        room._id = result.inserted_id
        return room

    @classmethod
    def get_by_room_id(cls, room_id: str) -> Optional["ChatRoom"]:
        """Fetch a room by its ``room_id`` field."""
        doc = get_rooms_collection().find_one({"room_id": room_id})
        return cls.from_dict(doc) if doc else None

    @classmethod
    def get_for_user(cls, user_id: str) -> list["ChatRoom"]:
        """Return all rooms where *user_id* is a participant."""
        cursor = get_rooms_collection().find({"participants": user_id})
        return [cls.from_dict(d) for d in cursor]

    def add_participant(self, user_id: str) -> None:
        """Add a participant to this room (idempotent)."""
        get_rooms_collection().update_one(
            {"room_id": self.room_id},
            {"$addToSet": {"participants": user_id}},
        )
        if user_id not in self.participants:
            self.participants.append(user_id)

    def remove_participant(self, user_id: str) -> None:
        """Remove a participant from this room."""
        get_rooms_collection().update_one(
            {"room_id": self.room_id},
            {"$pull": {"participants": user_id}},
        )
        self.participants = [p for p in self.participants if p != user_id]


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """
    Represents a single chat message stored in MongoDB.

    Attributes
    ----------
    room_id : str
        Foreign key to ``ChatRoom.room_id``.
    sender_id : str
        Django user ID of the message author.
    sender_username : str
        Display username (denormalised for read efficiency).
    content : str
        Plain-text message body.
    message_type : str
        One of ``"text"``, ``"image"``, ``"file"``.
    read_by : list[str]
        User IDs who have read this message.
    created_at : datetime
        UTC timestamp of delivery.
    _id : Optional[ObjectId]
        MongoDB ``_id`` field; ``None`` until inserted.
    """

    room_id: str
    sender_id: str
    sender_username: str
    content: str
    message_type: str = "text"
    read_by: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    _id: Optional[ObjectId] = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a dict suitable for MongoDB insertion."""
        d = asdict(self)
        d.pop("_id", None)
        return d

    def to_broadcast_dict(self) -> dict:
        """
        Return a JSON-serialisable dict safe to send over WebSocket.
        ``_id`` and ``ObjectId`` are converted to strings.
        """
        return {
            "id": str(self._id) if self._id else None,
            "room_id": self.room_id,
            "sender_id": self.sender_id,
            "sender_username": self.sender_username,
            "content": self.content,
            "message_type": self.message_type,
            "read_by": self.read_by,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        """Reconstruct a Message from a MongoDB document."""
        return cls(
            room_id=data["room_id"],
            sender_id=data["sender_id"],
            sender_username=data.get("sender_username", ""),
            content=data["content"],
            message_type=data.get("message_type", "text"),
            read_by=data.get("read_by", []),
            created_at=data.get("created_at", _now()),
            _id=data.get("_id"),
        )

    # ------------------------------------------------------------------
    # Class-level DB operations
    # ------------------------------------------------------------------

    @classmethod
    def send(
        cls,
        *,
        room_id: str,
        sender_id: str,
        sender_username: str,
        content: str,
        message_type: str = "text",
    ) -> "Message":
        """Persist a new message and return the populated instance."""
        msg = cls(
            room_id=room_id,
            sender_id=sender_id,
            sender_username=sender_username,
            content=content,
            message_type=message_type,
            read_by=[sender_id],    # sender has implicitly read their own message
        )
        result = get_messages_collection().insert_one(msg.to_dict())
        msg._id = result.inserted_id
        return msg

    @classmethod
    def history(
        cls,
        room_id: str,
        *,
        limit: int = 50,
        before: Optional[datetime] = None,
    ) -> list["Message"]:
        """
        Return the most recent *limit* messages for a room.

        Parameters
        ----------
        room_id : str
            The room to query.
        limit : int
            Maximum number of messages to return (default 50).
        before : datetime, optional
            If provided, return only messages created before this timestamp
            (useful for cursor-based pagination).
        """
        query: dict = {"room_id": room_id}
        if before:
            query["created_at"] = {"$lt": before}
        cursor = (
            get_messages_collection()
            .find(query)
            .sort("created_at", -1)
            .limit(limit)
        )
        # Reverse so oldest-first order suits chat UIs
        return [cls.from_dict(d) for d in reversed(list(cursor))]

    def mark_read(self, user_id: str) -> None:
        """Add *user_id* to the ``read_by`` array (idempotent)."""
        get_messages_collection().update_one(
            {"_id": self._id},
            {"$addToSet": {"read_by": user_id}},
        )
        if user_id not in self.read_by:
            self.read_by.append(user_id)
