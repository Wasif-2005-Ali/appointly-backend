"""
call/views.py — REST API views for the call app.

Endpoints
---------
GET  /api/call/history/         — List call history for the authenticated user
GET  /api/call/<call_id>/       — Get details of a specific call session
POST /api/call/<call_id>/end/   — End a call (fallback when the WS is dead)
"""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CallSession
from .serializers import CallSessionSerializer

logger = logging.getLogger(__name__)


class CallHistoryView(APIView):
    """
    GET /api/call/history/
    Returns the most recent 30 call sessions involving the requesting user.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        user_id = str(request.user.pk)
        sessions = CallSession.get_history_for_user(user_id, limit=30)
        return Response(
            CallSessionSerializer.from_sessions(sessions),
            status=status.HTTP_200_OK,
        )


class CallDetailView(APIView):
    """
    GET /api/call/<call_id>/
    Returns session metadata if the requesting user was caller or callee.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, call_id: str) -> Response:
        session = CallSession.get_by_call_id(call_id)
        if session is None:
            return Response(
                {"detail": f"Call session '{call_id}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        user_id = str(request.user.pk)
        if not session.is_participant(user_id):
            return Response(
                {"detail": "You are not a participant of this call."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            CallSessionSerializer.from_session(session),
            status=status.HTTP_200_OK,
        )


class CallEndView(APIView):
    """
    POST /api/call/<call_id>/end/
    End a call over REST — the fallback the app uses when its call
    WebSocket is dead (unexpected close, no reconnect) so the session
    does not stay stuck ``connected``.

    Auth + participant only. Idempotent: ending an already-terminal
    call returns its current state with 200. When the call actually
    transitions, a ``call.ended`` event is broadcast to the call group
    so a still-connected peer learns the call is over.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, call_id: str) -> Response:
        session = CallSession.get_by_call_id(call_id)
        if session is None:
            return Response(
                {"detail": f"Call session '{call_id}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        user_id = str(request.user.pk)
        if not session.is_participant(user_id):
            return Response(
                {"detail": "You are not a participant of this call."},
                status=status.HTTP_403_FORBIDDEN,
            )

        transitioned = session.end()
        if transitioned:
            self._broadcast_ended(session, user_id)

        return Response(
            CallSessionSerializer.from_session(session),
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _broadcast_ended(session: CallSession, ended_by: str) -> None:
        """Best-effort ``call.ended`` broadcast to the call group.

        A channel-layer failure must not fail the REST call itself —
        the session is already ended in the DB.
        """
        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                return
            async_to_sync(channel_layer.group_send)(
                f"call_{session.call_id}",
                {
                    "type": "call.ended",
                    "session": session.to_broadcast_dict(),
                    "ended_by": ended_by,
                },
            )
        except Exception:
            logger.exception(
                "Failed to broadcast call.ended for %s", session.call_id
            )
