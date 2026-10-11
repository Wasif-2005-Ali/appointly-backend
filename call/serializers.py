"""
call/serializers.py — DRF serializers for the call app.

CallSession instances reside in MongoDB, so we extend
``rest_framework.serializers.Serializer`` rather than ``ModelSerializer``.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import CallSession


class CallSessionSerializer(serializers.Serializer):
    """Read serializer for a CallSession document."""
    call_id          = serializers.CharField(read_only=True)
    caller_id        = serializers.CharField(read_only=True)
    callee_id        = serializers.CharField(read_only=True)
    call_type        = serializers.CharField(read_only=True)
    status           = serializers.CharField(read_only=True)
    started_at       = serializers.DateTimeField(read_only=True)
    connected_at     = serializers.DateTimeField(read_only=True, allow_null=True)
    ended_at         = serializers.DateTimeField(read_only=True, allow_null=True)
    duration_seconds = serializers.FloatField(read_only=True, allow_null=True)

    @classmethod
    def from_session(cls, session: CallSession) -> dict:
        return cls(session).data

    @classmethod
    def from_sessions(cls, sessions: list[CallSession]) -> list[dict]:
        return cls(sessions, many=True).data
