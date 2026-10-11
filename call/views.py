"""
call/views.py — REST API views for the call app.

Endpoints
---------
GET  /api/call/history/         — List call history for the authenticated user
GET  /api/call/<call_id>/       — Get details of a specific call session
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CallSession
from .serializers import CallSessionSerializer


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
