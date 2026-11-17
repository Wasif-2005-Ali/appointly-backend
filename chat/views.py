"""
chat/views.py — REST API views for the chat app.

Endpoint map
------------
GET  POST   /api/chat/rooms/                             RoomListCreateView
GET         /api/chat/rooms/<room_id>/                   RoomDetailView
POST        /api/chat/rooms/<room_id>/participants/add/  AddParticipantView
POST        /api/chat/rooms/<room_id>/participants/remove/ RemoveParticipantView
GET         /api/chat/rooms/<room_id>/messages/          MessageListView
POST        /api/chat/rooms/<room_id>/read/              MarkReadView
POST        /api/chat/rooms/<room_id>/media/             MediaUploadView

All endpoints require a valid Bearer (SimpleJWT) access token.
"""

from __future__ import annotations

import logging
from datetime import datetime

import cloudinary
import cloudinary.uploader
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ChatRoom, Message
from .serializers import (
    AddParticipantSerializer,
    ChatRoomSerializer,
    CreateRoomSerializer,
    MessageSerializer,
    RemoveParticipantSerializer,
)

User = get_user_model()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_room_or_404(room_id: str) -> ChatRoom | Response:
    """
    Return the ChatRoom or a 404 Response.
    Caller must check ``isinstance(result, Response)`` and return early.
    """
    room = ChatRoom.get_by_room_id(room_id)
    if room is None:
        return Response(
            {"detail": f"Room '{room_id}' not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return room


def _assert_member(room: ChatRoom, user_id: str) -> Response | None:
    """Return a 403 Response if user is not a participant, else None."""
    if user_id not in room.participants:
        return Response(
            {"detail": "You are not a member of this room."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _broadcast_message(room_id: str, message: dict) -> None:
    """
    Push a ``chat.message`` frame to every WebSocket client in the room.

    Same group name (``chat_<room_id>``) and event shape the WS consumer
    uses (chat/consumers.py), so clients handle media messages exactly
    like text ones — including the sender's own phone.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f"chat_{room_id}",
        {
            "type": "chat.message",
            "message": message,
        },
    )


# ---------------------------------------------------------------------------
# Room views
# ---------------------------------------------------------------------------

class RoomListCreateView(APIView):
    """
    GET  /api/chat/rooms/   — list all rooms the authenticated user belongs to.
    POST /api/chat/rooms/   — create a new room (creator is auto-added).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        rooms = ChatRoom.get_for_user(str(request.user.pk))
        return Response(
            ChatRoomSerializer(rooms, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request) -> Response:
        serializer = CreateRoomSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        creator_id = str(request.user.pk)

        # Build participant list: creator + any additional IDs provided
        raw_ids: list[str] = data.get("participant_ids", [])

        # Validate that every supplied user ID actually exists
        valid_ids: list[str] = []
        for uid in raw_ids:
            if uid == creator_id:
                continue                # creator added below unconditionally
            if not User.objects.filter(pk=uid).exists():
                return Response(
                    {"detail": f"User with id '{uid}' does not exist."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            valid_ids.append(uid)

        participants = [creator_id] + valid_ids

        room = ChatRoom.create(
            name=data["name"],
            participants=participants,
            is_group=data.get("is_group", False),
        )

        return Response(
            ChatRoomSerializer(room).data,
            status=status.HTTP_201_CREATED,
        )


class RoomDetailView(APIView):
    """
    GET /api/chat/rooms/<room_id>/  — room info (members only).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, room_id: str) -> Response:
        room = _get_room_or_404(room_id)
        if isinstance(room, Response):
            return room

        denied = _assert_member(room, str(request.user.pk))
        if denied:
            return denied

        return Response(ChatRoomSerializer(room).data)


# ---------------------------------------------------------------------------
# Participant management
# ---------------------------------------------------------------------------

class AddParticipantView(APIView):
    """
    POST /api/chat/rooms/<room_id>/participants/add/
    Body: { "user_id": "<pk>" }

    Only existing members may add others.  For group rooms only.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, room_id: str) -> Response:
        room = _get_room_or_404(room_id)
        if isinstance(room, Response):
            return room

        denied = _assert_member(room, str(request.user.pk))
        if denied:
            return denied

        if not room.is_group:
            return Response(
                {"detail": "Cannot add participants to a DM room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AddParticipantSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user_id: str = serializer.validated_data["user_id"]

        if not User.objects.filter(pk=user_id).exists():
            return Response(
                {"detail": f"User '{user_id}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        room.add_participant(user_id)
        return Response(ChatRoomSerializer(room).data)


class RemoveParticipantView(APIView):
    """
    POST /api/chat/rooms/<room_id>/participants/remove/
    Body: { "user_id": "<pk>" }

    Members may remove themselves; they cannot remove others
    (add admin logic here when needed).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, room_id: str) -> Response:
        room = _get_room_or_404(room_id)
        if isinstance(room, Response):
            return room

        denied = _assert_member(room, str(request.user.pk))
        if denied:
            return denied

        serializer = RemoveParticipantSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user_id: str = serializer.validated_data["user_id"]

        # Non-admin: you can only remove yourself
        if user_id != str(request.user.pk):
            return Response(
                {"detail": "You can only remove yourself from a room."},
                status=status.HTTP_403_FORBIDDEN,
            )

        room.remove_participant(user_id)
        return Response(
            {"detail": "You have left the room."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Message views
# ---------------------------------------------------------------------------

class MessageListView(APIView):
    """
    GET /api/chat/rooms/<room_id>/messages/

    Returns the 50 most recent messages, ordered oldest → newest.
    Supports cursor-based pagination via the ``before`` query param:

        GET /api/chat/rooms/<room_id>/messages/?before=2026-10-04T18:00:00Z

    Response shape
    --------------
    {
        "room_id": "...",
        "count": 42,
        "next_before": "<iso-datetime of the oldest message, for next page>",
        "messages": [ ... ]
    }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, room_id: str) -> Response:
        room = _get_room_or_404(room_id)
        if isinstance(room, Response):
            return room

        denied = _assert_member(room, str(request.user.pk))
        if denied:
            return denied

        # Parse optional cursor
        before: datetime | None = None
        raw_before: str = request.query_params.get("before", "")
        if raw_before:
            try:
                before = datetime.fromisoformat(raw_before)
            except ValueError:
                return Response(
                    {"detail": "Invalid 'before' datetime format. Use ISO 8601."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        messages = Message.history(room_id, limit=50, before=before)

        # Expose the oldest message's timestamp as the next cursor
        next_before = (
            messages[0].created_at.isoformat() if messages else None
        )

        return Response({
            "room_id": room_id,
            "count": len(messages),
            "next_before": next_before,
            "messages": MessageSerializer(messages, many=True).data,
        })


class MarkReadView(APIView):
    """
    POST /api/chat/rooms/<room_id>/read/

    Marks every message in the room sent by someone else as read by
    the requesting user (adds them to each message's ``read_by``).
    The app calls this when a thread is opened, so unread badges
    clear server-side and stay cleared across devices and restarts.

    Response: {"room_id": "...", "marked_read": <int>}
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, room_id: str) -> Response:
        room = _get_room_or_404(room_id)
        if isinstance(room, Response):
            return room

        denied = _assert_member(room, str(request.user.pk))
        if denied:
            return denied

        marked = Message.mark_room_read(room_id, str(request.user.pk))
        return Response(
            {"room_id": room_id, "marked_read": marked},
            status=status.HTTP_200_OK,
        )


class MediaUploadView(APIView):
    """
    POST /api/chat/rooms/<room_id>/media/

    Upload one file (multipart field ``file``) and send it as a chat
    message. The file is stored on Cloudinary; the created Message's
    ``content`` is the file's secure URL, so the other phone receives
    it live over the room WebSocket and in message history.

    ``message_type`` is inferred from the upload's content type:
    ``image/*`` → ``"image"``, anything else → ``"file"``.
    Size limits: images 10 MB, other files 25 MB.

    Requires Cloudinary to be configured on the server
    (CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET);
    otherwise returns 503.

    Response (201): the created message —
    {
        "id": "...", "room_id": "...", "sender_id": "...",
        "sender_username": "...", "content": "<secure_url>",
        "message_type": "image"|"file", "file_name": "...",
        "file_size": 12345, "read_by": ["..."],
        "created_at": "2026-11-17T..."
    }
    """

    permission_classes = [IsAuthenticated]

    MAX_IMAGE_BYTES = 10 * 1024 * 1024
    MAX_FILE_BYTES = 25 * 1024 * 1024

    def post(self, request: Request, room_id: str) -> Response:
        room = _get_room_or_404(room_id)
        if isinstance(room, Response):
            return room

        denied = _assert_member(room, str(request.user.pk))
        if denied:
            return denied

        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response(
                {"detail": "No file uploaded. Send the file as multipart field 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        content_type = (uploaded.content_type or "").lower()
        if content_type.startswith("image/"):
            message_type = "image"
            max_bytes = self.MAX_IMAGE_BYTES
        else:
            message_type = "file"
            max_bytes = self.MAX_FILE_BYTES

        if uploaded.size > max_bytes:
            return Response(
                {
                    "detail": (
                        f"File too large: {message_type} uploads are limited to "
                        f"{max_bytes // (1024 * 1024)} MB."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        cloud_name = settings.CLOUDINARY_CLOUD_NAME
        api_key = settings.CLOUDINARY_API_KEY
        api_secret = settings.CLOUDINARY_API_SECRET
        if not (cloud_name and api_key and api_secret):
            return Response(
                {"detail": "Media uploads are not configured on this server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )
        try:
            result = cloudinary.uploader.upload(
                uploaded,
                folder=f"appointly/chat/{room_id}",
                resource_type="auto",
            )
        except Exception:
            logger.exception("Cloudinary upload failed for room %s", room_id)
            return Response(
                {"detail": "Media upload failed. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        secure_url = result.get("secure_url")
        if not secure_url:
            logger.error("Cloudinary upload returned no secure_url for room %s", room_id)
            return Response(
                {"detail": "Media upload failed. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        msg = Message.send(
            room_id=room_id,
            sender_id=str(request.user.pk),
            sender_username=request.user.get_username(),
            content=secure_url,
            message_type=message_type,
            file_name=uploaded.name,
            file_size=uploaded.size,
        )

        _broadcast_message(room_id, msg.to_broadcast_dict())

        return Response(
            MessageSerializer(msg).data,
            status=status.HTTP_201_CREATED,
        )
