"""
chat/views.py — REST API views for the chat app.

Endpoint map
------------
GET  POST   /api/chat/rooms/                             RoomListCreateView
GET         /api/chat/rooms/<room_id>/                   RoomDetailView
POST        /api/chat/rooms/<room_id>/participants/add/  AddParticipantView
POST        /api/chat/rooms/<room_id>/participants/remove/ RemoveParticipantView
GET         /api/chat/rooms/<room_id>/messages/          MessageListView

All endpoints require a valid Bearer (SimpleJWT) access token.
"""

from __future__ import annotations

from datetime import datetime

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
