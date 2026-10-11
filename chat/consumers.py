"""
chat/consumers.py — WebSocket consumer for real-time chat.

Flow
----
1. Client connects to  ws://<host>/ws/chat/<room_id>/
2. Consumer authenticates via JWT query-param  ?token=<access_token>
3. Consumer joins the Channels group  "chat_<room_id>"
4. On receive: message is persisted to MongoDB then broadcast to the group
5. On disconnect: consumer leaves the group

Message frames (JSON)
----------------------
Client → Server
    { "type": "chat.message", "content": "Hello!", "message_type": "text" }

Server → Client
    {
        "type": "chat.message",
        "message": {
            "id": "...",
            "room_id": "...",
            "sender_id": "...",
            "sender_username": "...",
            "content": "Hello!",
            "message_type": "text",
            "read_by": ["..."],
            "created_at": "2026-10-05T..."
        }
    }

Error frames (Server → Client)
    { "type": "error", "code": "...", "detail": "..." }

History request (Client → Server)
    { "type": "chat.history", "before": "<iso-datetime or null>" }

History response (Server → Client)
    { "type": "chat.history", "messages": [...] }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async

from .models import ChatRoom, Message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JWT helper (sync — called via database_sync_to_async)
# ---------------------------------------------------------------------------

def _get_user_from_token(token: str):
    """
    Validate a SimpleJWT access token and return the Django User instance,
    or None if the token is invalid / expired.
    """
    from rest_framework_simplejwt.tokens import AccessToken
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        validated = AccessToken(token)
        user_id = validated["user_id"]
        return User.objects.get(pk=user_id)
    except (InvalidToken, TokenError, User.DoesNotExist, KeyError):
        return None


# ---------------------------------------------------------------------------
# Main consumer
# ---------------------------------------------------------------------------

class ChatConsumer(AsyncJsonWebsocketConsumer):
    """
    Async WebSocket consumer that handles real-time messaging for a
    single chat room.

    URL pattern:  ws://<host>/ws/chat/<room_id>/
    Query params: ?token=<SimpleJWT access token>
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """
        Authenticate the user, validate the room, and accept/reject
        the WebSocket connection.
        """
        # 1. Extract JWT from query string
        query_string: bytes = self.scope.get("query_string", b"")
        params = dict(
            pair.split(b"=", 1)
            for pair in query_string.split(b"&")
            if b"=" in pair
        )
        token: str = params.get(b"token", b"").decode()

        # 2. Authenticate
        self.user = await database_sync_to_async(_get_user_from_token)(token)
        if self.user is None:
            await self.close(code=4001)
            return

        # 3. Validate room
        self.room_id: str = self.scope["url_route"]["kwargs"]["room_id"]
        room: ChatRoom | None = await database_sync_to_async(
            ChatRoom.get_by_room_id
        )(self.room_id)

        if room is None:
            await self.close(code=4004)
            return

        # Optional: enforce membership
        if str(self.user.pk) not in room.participants:
            await self.close(code=4003)
            return

        # 4. Join Channels group
        self.group_name: str = f"chat_{self.room_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        await self.accept()
        logger.info(
            "WS connect: user=%s room=%s channel=%s",
            self.user.pk,
            self.room_id,
            self.channel_name,
        )

    async def disconnect(self, close_code: int) -> None:
        """Leave the channel group on disconnect."""
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )
        logger.info(
            "WS disconnect: user=%s room=%s code=%s",
            getattr(self, "user", "?"),
            getattr(self, "room_id", "?"),
            close_code,
        )

    # ------------------------------------------------------------------
    # Inbound frames from client
    # ------------------------------------------------------------------

    async def receive_json(self, content: dict, **kwargs) -> None:
        """Dispatch incoming JSON frames to the appropriate handler."""
        frame_type: str = content.get("type", "")

        if frame_type == "chat.message":
            await self._handle_chat_message(content)
        elif frame_type == "chat.history":
            await self._handle_history_request(content)
        else:
            await self.send_json({
                "type": "error",
                "code": "unknown_type",
                "detail": f"Unknown frame type: '{frame_type}'",
            })

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_chat_message(self, content: dict) -> None:
        """Persist a message to MongoDB and broadcast it to the room."""
        raw_content: str = (content.get("content") or "").strip()
        if not raw_content:
            await self.send_json({
                "type": "error",
                "code": "empty_message",
                "detail": "Message content must not be empty.",
            })
            return

        message_type: str = content.get("message_type", "text")
        if message_type not in {"text", "image", "file"}:
            message_type = "text"

        # Persist to MongoDB (sync call on thread pool)
        msg: Message = await database_sync_to_async(Message.send)(
            room_id=self.room_id,
            sender_id=str(self.user.pk),
            sender_username=self.user.get_username(),
            content=raw_content,
            message_type=message_type,
        )

        # Broadcast to all members of the group (including the sender)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.message",         # maps to chat_message() below
                "message": msg.to_broadcast_dict(),
            },
        )

    async def _handle_history_request(self, content: dict) -> None:
        """
        Return paginated message history to the requesting client only.
        Accepts an ISO-format ``before`` timestamp for cursor pagination.
        """
        before: datetime | None = None
        raw_before: str = content.get("before") or ""
        if raw_before:
            try:
                before = datetime.fromisoformat(raw_before)
            except ValueError:
                await self.send_json({
                    "type": "error",
                    "code": "invalid_before",
                    "detail": "``before`` must be a valid ISO-8601 datetime string.",
                })
                return

        messages: list[Message] = await database_sync_to_async(
            Message.history
        )(self.room_id, limit=50, before=before)

        await self.send_json({
            "type": "chat.history",
            "messages": [m.to_broadcast_dict() for m in messages],
        })

    # ------------------------------------------------------------------
    # Group event handlers (called by channel_layer.group_send)
    # ------------------------------------------------------------------

    async def chat_message(self, event: dict) -> None:
        """
        Forward a ``chat.message`` group event to the WebSocket client.
        Channels maps the dot-separated type to this method name.
        """
        await self.send_json({
            "type": "chat.message",
            "message": event["message"],
        })
