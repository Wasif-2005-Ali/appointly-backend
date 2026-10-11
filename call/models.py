"""
call/models.py — PyMongo document model for a WebRTC call session.

Collection
----------
  call_sessions  — one document per call attempt, updated in-place as
                   the call progresses through its state machine.

State machine
-------------

  ┌─────────┐   call.initiate   ┌─────────┐
  │  (none)  │ ───────────────► │ ringing │
  └─────────┘                   └────┬────┘
                                     │
              ┌──────────────────────┼─────────────────────┐
              │                      │                      │
              ▼                      ▼                      ▼
         call.accept           call.reject             call.miss
              │                      │               (timeout / no answer)
              ▼                      ▼                      ▼
         ┌───────────┐         ┌──────────┐          ┌────────┐
         │ connected │         │ rejected │          │ missed │
         └─────┬─────┘         └──────────┘          └────────┘
               │
          call.end
               │
               ▼
          ┌────────┐
          │ ended  │
          └────────┘

Documents are never deleted — ended/missed/rejected sessions form the
call history shown in the UI.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from .db import get_sessions_collection


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

class CallStatus:
    RINGING   = "ringing"
    CONNECTED = "connected"
    ENDED     = "ended"
    REJECTED  = "rejected"
    MISSED    = "missed"

    ALL = {RINGING, CONNECTED, ENDED, REJECTED, MISSED}

    # Terminal statuses — no further transitions allowed
    TERMINAL = {ENDED, REJECTED, MISSED}


# ---------------------------------------------------------------------------
# CallSession
# ---------------------------------------------------------------------------

@dataclass
class CallSession:
    """
    Represents a single call attempt between two users.

    Attributes
    ----------
    call_id : str
        UUID4 hex string used in WebSocket URLs and channel group names.
    caller_id : str
        Django user PK of the user who initiated the call.
    callee_id : str
        Django user PK of the user being called.
    call_type : str
        ``"audio"`` or ``"video"``.
    status : str
        Current state — see :class:`CallStatus`.
    started_at : datetime
        UTC timestamp of call creation (when ``call.initiate`` was received).
    connected_at : datetime or None
        UTC timestamp of when the callee accepted.
    ended_at : datetime or None
        UTC timestamp of final state (ended / rejected / missed).
    duration_seconds : float or None
        Wall-clock seconds from ``connected_at`` to ``ended_at``.
        ``None`` if the call never connected.
    _id : ObjectId or None
        MongoDB internal ``_id``; ``None`` until inserted.
    """

    call_id:          str
    caller_id:        str
    callee_id:        str
    call_type:        str                    = "video"
    status:           str                    = CallStatus.RINGING
    started_at:       datetime               = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    connected_at:     Optional[datetime]     = None
    ended_at:         Optional[datetime]     = None
    duration_seconds: Optional[float]        = None
    _id:              Optional[ObjectId]     = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def generate_call_id(cls) -> str:
        """Return a fresh UUID4 hex string (no dashes, 32 chars)."""
        return uuid.uuid4().hex

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a MongoDB-insertable dict (no ``_id``)."""
        d = asdict(self)
        d.pop("_id", None)
        return d

    def to_broadcast_dict(self) -> dict:
        """Return a JSON-serialisable dict safe to send over WebSocket."""
        return {
            "call_id":          self.call_id,
            "caller_id":        self.caller_id,
            "callee_id":        self.callee_id,
            "call_type":        self.call_type,
            "status":           self.status,
            "started_at":       self.started_at.isoformat(),
            "connected_at":     self.connected_at.isoformat() if self.connected_at else None,
            "ended_at":         self.ended_at.isoformat()     if self.ended_at     else None,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CallSession":
        return cls(
            call_id=          data["call_id"],
            caller_id=        data["caller_id"],
            callee_id=        data["callee_id"],
            call_type=        data.get("call_type", "video"),
            status=           data.get("status", CallStatus.RINGING),
            started_at=       data.get("started_at", datetime.now(tz=timezone.utc)),
            connected_at=     data.get("connected_at"),
            ended_at=         data.get("ended_at"),
            duration_seconds= data.get("duration_seconds"),
            _id=              data.get("_id"),
        )

    # ------------------------------------------------------------------
    # DB operations — class methods
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        call_id:   str,
        caller_id: str,
        callee_id: str,
        call_type: str = "video",
    ) -> "CallSession":
        """Insert a new ringing session and return the instance."""
        session = cls(
            call_id=call_id,
            caller_id=caller_id,
            callee_id=callee_id,
            call_type=call_type,
        )
        result = get_sessions_collection().insert_one(session.to_dict())
        session._id = result.inserted_id
        return session

    @classmethod
    def get_by_call_id(cls, call_id: str) -> Optional["CallSession"]:
        doc = get_sessions_collection().find_one({"call_id": call_id})
        return cls.from_dict(doc) if doc else None

    @classmethod
    def get_history_for_user(cls, user_id: str, *, limit: int = 30) -> list["CallSession"]:
        """Return the most recent *limit* call sessions involving *user_id*."""
        cursor = (
            get_sessions_collection()
            .find({"$or": [{"caller_id": user_id}, {"callee_id": user_id}]})
            .sort("started_at", -1)
            .limit(limit)
        )
        return [cls.from_dict(d) for d in cursor]

    # ------------------------------------------------------------------
    # State transitions — instance methods
    # ------------------------------------------------------------------

    def _apply_update(self, update: dict) -> None:
        """Apply a ``$set`` update to MongoDB and refresh this instance."""
        get_sessions_collection().update_one(
            {"call_id": self.call_id},
            {"$set": update},
        )
        for k, v in update.items():
            setattr(self, k, v)

    def accept(self) -> None:
        """Transition: ringing → connected."""
        now = datetime.now(tz=timezone.utc)
        self._apply_update({
            "status":       CallStatus.CONNECTED,
            "connected_at": now,
        })

    def reject(self) -> None:
        """Transition: ringing → rejected."""
        now = datetime.now(tz=timezone.utc)
        self._apply_update({
            "status":   CallStatus.REJECTED,
            "ended_at": now,
        })

    def miss(self) -> None:
        """Transition: ringing → missed (called by a server-side timeout task)."""
        now = datetime.now(tz=timezone.utc)
        self._apply_update({
            "status":   CallStatus.MISSED,
            "ended_at": now,
        })

    def end(self) -> None:
        """Transition: connected → ended (or ringing → ended if caller hangs up)."""
        now = datetime.now(tz=timezone.utc)
        duration = None
        if self.connected_at:
            duration = (now - self.connected_at).total_seconds()
        self._apply_update({
            "status":           CallStatus.ENDED,
            "ended_at":         now,
            "duration_seconds": duration,
        })

    @property
    def is_terminal(self) -> bool:
        """True if no further state transitions are allowed."""
        return self.status in CallStatus.TERMINAL

    def is_participant(self, user_id: str) -> bool:
        return user_id in {self.caller_id, self.callee_id}
