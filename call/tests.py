"""
call/tests.py — Tests for the CallSession state machine and the
CallConsumer signaling flow.

No MongoDB server is available in the test environment, so the
``call_sessions`` collection is replaced with a small in-memory fake
that implements the PyMongo methods the model uses
(``insert_one`` / ``find_one`` / ``update_one`` / ``find`` + cursor
``sort`` / ``limit``). The fake is patched onto
``call.models.get_sessions_collection``, which is the exact function
``CallSession`` calls.
"""

from __future__ import annotations

import uuid
from unittest import mock

from bson import ObjectId
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from call.models import CallSession, CallStatus
from call.routing import websocket_urlpatterns


# ---------------------------------------------------------------------------
# In-memory fake for the ``call_sessions`` MongoDB collection
# ---------------------------------------------------------------------------

class _FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction=-1):
        self._docs.sort(key=lambda d: d.get(key), reverse=(direction == -1))
        return self

    def limit(self, n):
        return self._docs[:n]

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    """Minimal in-memory stand-in for a PyMongo collection."""

    def __init__(self):
        self._docs = {}

    def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = ObjectId()
        self._docs[doc["call_id"]] = doc
        return _FakeInsertResult(doc["_id"])

    def find_one(self, filter):
        doc = self._docs.get(filter.get("call_id"))
        return dict(doc) if doc is not None else None

    def update_one(self, filter, update):
        doc = self._docs.get(filter.get("call_id"))
        if doc is None:
            return
        for key, value in update.get("$set", {}).items():
            doc[key] = value

    def find(self, filter):
        docs = list(self._docs.values())
        or_clauses = filter.get("$or")
        if or_clauses:
            docs = [
                d
                for d in docs
                if any(
                    all(d.get(k) == v for k, v in clause.items())
                    for clause in or_clauses
                )
            ]
        return _FakeCursor(docs)


class CallSessionTestMixin:
    """Patch the sessions collection with the in-memory fake."""

    def setUp(self):
        super().setUp()
        self._fake_collection = _FakeCollection()
        patcher = mock.patch(
            "call.models.get_sessions_collection",
            return_value=self._fake_collection,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_session(self, caller_id="1", callee_id="2", call_type="video"):
        return CallSession.create(
            call_id=uuid.uuid4().hex,
            caller_id=caller_id,
            callee_id=callee_id,
            call_type=call_type,
        )


class CallSessionModelTests(CallSessionTestMixin, TransactionTestCase):
    def test_end_from_stale_caller_copy_records_duration(self):
        """Caller ends a connected call: duration must not be null.

        Regression test for the live bug where the caller's consumer
        held a pre-accept copy (connected_at=None) and end() stored
        duration_seconds=None. end() must reload the session from the
        DB so the real connected_at is used.
        """
        session = self.make_session()
        stale_caller_copy = CallSession.get_by_call_id(session.call_id)
        session.accept()

        stale_caller_copy.end()

        fresh = CallSession.get_by_call_id(session.call_id)
        self.assertEqual(fresh.status, CallStatus.ENDED)
        self.assertIsNotNone(fresh.duration_seconds)
        self.assertGreaterEqual(fresh.duration_seconds, 0)

    def test_end_before_connect_is_missed_not_ended(self):
        """A call ended while still ringing lands in history as missed."""
        session = self.make_session()
        session.end()

        fresh = CallSession.get_by_call_id(session.call_id)
        self.assertEqual(fresh.status, CallStatus.MISSED)
        self.assertIsNone(fresh.duration_seconds)
        self.assertIsNotNone(fresh.ended_at)

    def test_reject_stays_rejected_when_caller_ends_afterwards(self):
        """An explicit callee reject is not overwritten by a late end."""
        session = self.make_session()
        stale_caller_copy = CallSession.get_by_call_id(session.call_id)
        session.reject()

        stale_caller_copy.end()

        fresh = CallSession.get_by_call_id(session.call_id)
        self.assertEqual(fresh.status, CallStatus.REJECTED)
        self.assertIsNone(fresh.duration_seconds)

    def test_connected_call_ends_with_duration(self):
        session = self.make_session()
        session.accept()
        session.end()

        fresh = CallSession.get_by_call_id(session.call_id)
        self.assertEqual(fresh.status, CallStatus.ENDED)
        self.assertIsNotNone(fresh.duration_seconds)


class CallConsumerTests(CallSessionTestMixin, TransactionTestCase):
    """End-to-end signaling tests over WebSocket (in-memory channel layer)."""

    def setUp(self):
        super().setUp()
        user_model = get_user_model()
        self.caller = user_model.objects.create_user(
            email="caller@test.com", full_name="Caller",
            profession="Tester", password="TestPass123!",
        )
        self.callee = user_model.objects.create_user(
            email="callee@test.com", full_name="Callee",
            profession="Tester", password="TestPass123!",
        )
        self.application = URLRouter(websocket_urlpatterns)
        # Tokens must be minted in sync setUp: RefreshToken.for_user hits
        # the DB and cannot run inside the async test methods.
        self._tokens = {
            str(self.caller.pk): str(RefreshToken.for_user(self.caller).access_token),
            str(self.callee.pk): str(RefreshToken.for_user(self.callee).access_token),
        }

    def _token(self, user):
        return self._tokens[str(user.pk)]

    def _communicator(self, user, call_id):
        return WebsocketCommunicator(
            self.application,
            f"/ws/call/{call_id}/?token={self._token(user)}",
        )

    async def _connect_call(self):
        """Connect caller + callee, initiate, accept. Returns communicators."""
        call_id = uuid.uuid4().hex
        ws_caller = self._communicator(self.caller, call_id)
        connected, _ = await ws_caller.connect()
        self.assertTrue(connected)

        await ws_caller.send_json_to({
            "type": "call.initiate",
            "callee_id": str(self.callee.pk),
            "call_type": "video",
        })
        initiated = await ws_caller.receive_json_from(timeout=5)
        self.assertEqual(initiated["type"], "call.initiated")
        self.assertEqual(initiated["session"]["status"], "ringing")

        ws_callee = self._communicator(self.callee, call_id)
        connected, _ = await ws_callee.connect()
        self.assertTrue(connected)

        peer = await ws_caller.receive_json_from(timeout=5)
        self.assertEqual(peer["type"], "call.peer_connected")

        await ws_callee.send_json_to({"type": "call.accept"})
        callee_accepted = await ws_callee.receive_json_from(timeout=5)
        caller_accepted = await ws_caller.receive_json_from(timeout=5)
        self.assertEqual(callee_accepted["type"], "call.accepted")
        self.assertEqual(caller_accepted["type"], "call.accepted")
        self.assertEqual(callee_accepted["session"]["status"], "connected")
        return ws_caller, ws_callee, call_id

    async def test_caller_ends_connected_call_records_duration(self):
        """Fix 3 over the real consumer: caller ends -> duration not null."""
        ws_caller, ws_callee, call_id = await self._connect_call()

        await ws_caller.send_json_to({"type": "call.end"})
        caller_ended = await ws_caller.receive_json_from(timeout=5)
        callee_ended = await ws_callee.receive_json_from(timeout=5)
        self.assertEqual(caller_ended["type"], "call.ended")
        self.assertEqual(callee_ended["type"], "call.ended")
        self.assertEqual(caller_ended["session"]["status"], "ended")
        self.assertIsNotNone(caller_ended["session"]["duration_seconds"])
        self.assertGreaterEqual(caller_ended["session"]["duration_seconds"], 0)

        session = CallSession.get_by_call_id(call_id)
        self.assertEqual(session.status, CallStatus.ENDED)
        self.assertIsNotNone(session.duration_seconds)

        await ws_caller.disconnect()
        await ws_callee.disconnect()

    async def test_callee_ends_connected_call_records_duration(self):
        ws_caller, ws_callee, call_id = await self._connect_call()

        await ws_callee.send_json_to({"type": "call.end"})
        caller_ended = await ws_caller.receive_json_from(timeout=5)
        callee_ended = await ws_callee.receive_json_from(timeout=5)
        self.assertEqual(caller_ended["session"]["status"], "ended")
        self.assertIsNotNone(callee_ended["session"]["duration_seconds"])

        session = CallSession.get_by_call_id(call_id)
        self.assertEqual(session.status, CallStatus.ENDED)
        self.assertIsNotNone(session.duration_seconds)

        await ws_caller.disconnect()
        await ws_callee.disconnect()

    async def test_unanswered_call_ended_by_caller_is_missed(self):
        """Fix 4 over the real consumer: no answer + caller hangs up = missed."""
        call_id = uuid.uuid4().hex
        ws_caller = self._communicator(self.caller, call_id)
        connected, _ = await ws_caller.connect()
        self.assertTrue(connected)

        await ws_caller.send_json_to({
            "type": "call.initiate",
            "callee_id": str(self.callee.pk),
            "call_type": "video",
        })
        initiated = await ws_caller.receive_json_from(timeout=5)
        self.assertEqual(initiated["session"]["status"], "ringing")

        await ws_caller.send_json_to({"type": "call.end"})
        ended = await ws_caller.receive_json_from(timeout=5)
        self.assertEqual(ended["type"], "call.ended")
        self.assertEqual(ended["session"]["status"], "missed")
        self.assertIsNone(ended["session"]["duration_seconds"])

        session = CallSession.get_by_call_id(call_id)
        self.assertEqual(session.status, CallStatus.MISSED)

        await ws_caller.disconnect()

    async def test_callee_reject_stays_rejected(self):
        call_id = uuid.uuid4().hex
        ws_caller = self._communicator(self.caller, call_id)
        connected, _ = await ws_caller.connect()
        self.assertTrue(connected)

        await ws_caller.send_json_to({
            "type": "call.initiate",
            "callee_id": str(self.callee.pk),
            "call_type": "video",
        })
        await ws_caller.receive_json_from(timeout=5)

        ws_callee = self._communicator(self.callee, call_id)
        connected, _ = await ws_callee.connect()
        self.assertTrue(connected)
        await ws_caller.receive_json_from(timeout=5)  # call.peer_connected

        await ws_callee.send_json_to({"type": "call.reject"})
        rejected = await ws_callee.receive_json_from(timeout=5)
        await ws_caller.receive_json_from(timeout=5)
        self.assertEqual(rejected["type"], "call.rejected")
        self.assertEqual(rejected["session"]["status"], "rejected")

        session = CallSession.get_by_call_id(call_id)
        self.assertEqual(session.status, CallStatus.REJECTED)

        await ws_caller.disconnect()
        await ws_callee.disconnect()
