"""
chat/serializers.py — DRF serializers for the chat app.

Because ChatRoom and Message live in MongoDB (not the Django ORM),
all serializers extend ``rest_framework.serializers.Serializer``
rather than ``ModelSerializer``.  They validate inbound data and
convert outbound PyMongo dataclass instances into plain dicts.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import ChatRoom, Message


# ---------------------------------------------------------------------------
# ChatRoom serializers
# ---------------------------------------------------------------------------

class ChatRoomSerializer(serializers.Serializer):
    """Read serializer — safe to use for any ChatRoom response."""
    room_id      = serializers.CharField(read_only=True)
    name         = serializers.CharField(read_only=True)
    participants = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_group     = serializers.BooleanField(read_only=True)
    created_at   = serializers.DateTimeField(read_only=True)

    @classmethod
    def from_room(cls, room: ChatRoom) -> dict:
        """Shortcut: serialise a ChatRoom instance to a dict."""
        return cls(room).data


class CreateRoomSerializer(serializers.Serializer):
    """Write serializer — validates POST /api/chat/rooms/ body."""

    name            = serializers.CharField(max_length=120)
    participant_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Additional Django user PKs to add besides the creator.",
    )
    is_group = serializers.BooleanField(default=False)

    def validate_name(self, value: str) -> str:
        return value.strip()

    def validate(self, data: dict) -> dict:
        if not data.get("is_group") and len(data.get("participant_ids", [])) > 1:
            raise serializers.ValidationError(
                "A non-group (DM) room may only have one additional participant."
            )
        return data


class AddParticipantSerializer(serializers.Serializer):
    """Validates POST /api/chat/rooms/<room_id>/participants/add/"""
    user_id = serializers.CharField()


class RemoveParticipantSerializer(serializers.Serializer):
    """Validates POST /api/chat/rooms/<room_id>/participants/remove/"""
    user_id = serializers.CharField()


# ---------------------------------------------------------------------------
# Message serializers
# ---------------------------------------------------------------------------

class MessageSerializer(serializers.Serializer):
    """Read serializer for a Message document."""
    id               = serializers.SerializerMethodField()
    room_id          = serializers.CharField(read_only=True)
    sender_id        = serializers.CharField(read_only=True)
    sender_username  = serializers.CharField(read_only=True)
    content          = serializers.CharField(read_only=True)
    message_type     = serializers.CharField(read_only=True)
    read_by          = serializers.ListField(child=serializers.CharField(), read_only=True)
    created_at       = serializers.DateTimeField(read_only=True)

    def get_id(self, obj: Message) -> str | None:
        return str(obj._id) if obj._id else None

    @classmethod
    def from_message(cls, msg: Message) -> dict:
        return cls(msg).data

    @classmethod
    def from_messages(cls, msgs: list[Message]) -> list[dict]:
        return cls(msgs, many=True).data
