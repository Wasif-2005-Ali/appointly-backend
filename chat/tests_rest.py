"""
chat/tests_rest.py — REST + model tests for the chat app.

No MongoDB server is available in the test environment, so the
``chat_messages`` collection is replaced with a small in-memory fake
that implements the PyMongo methods the Message model uses
(``insert_one`` / ``find_one`` / ``aggregate`` for the pipelines in
``last_messages_for_rooms`` / ``unread_counts_for_rooms``). The fake is
patched onto ``chat.models.get_messages_collection``, which is the
exact function the model calls.

Covers:
  FIX 6 — reply quotes (model round-trip + REST list fields)
  FIX 7 — MarkReadView broadcasts ``chat.read``
  FIX 8 — rooms list carries ``last_message`` / ``unread_count``
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import User
from chat.models import ChatRoom, Message


# ---------------------------------------------------------------------------
# In-memory fake for the ``chat_messages`` MongoDB collection
# ---------------------------------------------------------------------------

class _FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class _FakeMessagesCollection:
    """Minimal in-memory stand-in for a PyMongo collection.

    Reads strip tzinfo from datetimes, exactly like real PyMongo
    without ``tz_aware=True``: the stored value keeps its tzinfo, but
    what a reader gets back is naive (``from_dict`` normalises it
    back to aware UTC).

    ``aggregate`` interprets the pipeline stages the Message model
    uses: ``$match`` (equality, ``$in``, ``$ne`` — with Mongo's
    array semantics for ``$ne`` on list fields), ``$sort``, and
    ``$group`` (``$first: "$$ROOT"`` and ``$sum: 1``).
    """

    def __init__(self):
        self._docs = []
        self.aggregate_calls = 0

    @staticmethod
    def _strip_tzinfo(doc):
        return {
            k: (v.replace(tzinfo=None)
                if isinstance(v, datetime) and v.tzinfo is not None else v)
            for k, v in doc.items()
        }

    def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = ObjectId()
        self._docs.append(doc)
        return _FakeInsertResult(doc["_id"])

    def find_one(self, filter):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in filter.items()):
                return self._strip_tzinfo(doc)
        return None

    def aggregate(self, pipeline):
        self.aggregate_calls += 1
        docs = [dict(d) for d in self._docs]
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if self._matches(d, stage["$match"])]
            elif "$sort" in stage:
                for key, direction in reversed(list(stage["$sort"].items())):
                    docs.sort(
                        key=lambda d: d.get(key),
                        reverse=(direction == -1),
                    )
            elif "$group" in stage:
                docs = self._group(docs, stage["$group"])
            else:
                raise NotImplementedError(
                    f"fake aggregate: unsupported stage {stage!r}"
                )
        return [self._strip_tzinfo(d) for d in docs]

    @staticmethod
    def _matches(doc, query):
        for field, cond in query.items():
            value = doc.get(field)
            if isinstance(cond, dict):
                for op, operand in cond.items():
                    if op == "$in":
                        if value not in operand:
                            return False
                    elif op == "$ne":
                        # On array fields (read_by) $ne matches when
                        # NO element equals the operand.
                        if isinstance(value, list):
                            if operand in value:
                                return False
                        elif value == operand:
                            return False
                    else:
                        raise NotImplementedError(
                            f"fake $match: unsupported op {op}"
                        )
            elif value != cond:
                return False
        return True

    @staticmethod
    def _group(docs, spec):
        key_field = spec["_id"].lstrip("$")
        groups = {}
        order = []
        for doc in docs:
            key = doc.get(key_field)
            if key not in groups:
                groups[key] = {"_id": key}
                order.append(key)
                for out_field, expr in spec.items():
                    if out_field == "_id":
                        continue
                    if "$first" in expr:
                        groups[key][out_field] = (
                            doc if expr["$first"] == "$$ROOT"
                            else doc.get(expr["$first"].lstrip("$"))
                        )
                    elif "$sum" in expr:
                        groups[key][out_field] = 0
            for out_field, expr in spec.items():
                if out_field != "_id" and "$sum" in expr:
                    groups[key][out_field] += expr["$sum"]
        return [groups[k] for k in order]


class MessageFakeCollectionMixin:
    """Patch the messages collection with the in-memory fake."""

    def setUp(self):
        super().setUp()
        self._fake_messages = _FakeMessagesCollection()
        patcher = patch(
            "chat.models.get_messages_collection",
            return_value=self._fake_messages,
        )
        patcher.start()
        self.addCleanup(patcher.stop)


def _ts(hour):
    """Aware UTC datetime on a fixed day, for ordering messages."""
    return datetime(2026, 11, 18, hour, 0, 0, tzinfo=timezone.utc)


def _make_user(email, name):
    return User.objects.create_user(
        email=email, full_name=name,
        profession="Tester", password="TestPass123!",
    )


# ---------------------------------------------------------------------------
# FIX 6 — reply quotes: model + REST
# ---------------------------------------------------------------------------

class MessageReplyModelTests(MessageFakeCollectionMixin, TestCase):
    def test_reply_fields_round_trip_through_mongo(self):
        msg = Message.send(
            room_id="room-reply-01",
            sender_id="1",
            sender_username="replier",
            content="Agreed!",
            reply_to_id="507f1f77bcf86cd799439011",
            reply_to_text="Shall we meet at 5?",
        )

        stored = self._fake_messages.find_one({"_id": msg._id})
        self.assertEqual(stored["reply_to_id"], "507f1f77bcf86cd799439011")
        self.assertEqual(stored["reply_to_text"], "Shall we meet at 5?")

        reloaded = Message.from_dict(stored)
        self.assertEqual(reloaded.reply_to_id, "507f1f77bcf86cd799439011")
        self.assertEqual(reloaded.reply_to_text, "Shall we meet at 5?")

        broadcast = reloaded.to_broadcast_dict()
        self.assertEqual(broadcast["reply_to_id"], "507f1f77bcf86cd799439011")
        self.assertEqual(broadcast["reply_to_text"], "Shall we meet at 5?")

    def test_messages_without_reply_fields_read_back_as_none(self):
        """Old documents (written before reply quotes existed) lack the
        fields entirely — they must read back as None, not crash."""
        msg = Message.send(
            room_id="room-reply-01",
            sender_id="1",
            sender_username="replier",
            content="Plain message.",
        )
        stored = self._fake_messages.find_one({"_id": msg._id})
        del stored["reply_to_id"]
        del stored["reply_to_text"]

        reloaded = Message.from_dict(stored)
        self.assertIsNone(reloaded.reply_to_id)
        self.assertIsNone(reloaded.reply_to_text)
        self.assertIsNone(reloaded.to_broadcast_dict()["reply_to_id"])
        self.assertIsNone(reloaded.to_broadcast_dict()["reply_to_text"])


class MessageReplyRestTests(TestCase):
    """GET /api/chat/rooms/<room_id>/messages/ includes reply fields."""

    def setUp(self):
        self.client = APIClient()
        self.me = _make_user("reply.me@example.com", "Reply Me")
        self.other = _make_user("reply.other@example.com", "Reply Other")
        access = str(RefreshToken.for_user(self.me).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        self.room = ChatRoom(
            room_id="reply-room-01",
            name="Reply room",
            participants=[str(self.me.pk), str(self.other.pk)],
        )
        self.msg = Message(
            room_id="reply-room-01",
            sender_id=str(self.other.pk),
            sender_username="replyother",
            content="Agreed!",
            reply_to_id="507f1f77bcf86cd799439011",
            reply_to_text="Shall we meet at 5?",
            read_by=[str(self.other.pk)],
            _id=ObjectId(),
        )
        self._patchers = [
            patch("chat.views.ChatRoom.get_by_room_id",
                  return_value=self.room),
            patch("chat.views.Message.history",
                  return_value=[self.msg]),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_message_list_includes_reply_fields(self):
        response = self.client.get("/api/chat/rooms/reply-room-01/messages/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        item = response.data["messages"][0]
        self.assertEqual(item["reply_to_id"], "507f1f77bcf86cd799439011")
        self.assertEqual(item["reply_to_text"], "Shall we meet at 5?")


# ---------------------------------------------------------------------------
# FIX 7 — MarkReadView broadcasts chat.read
# ---------------------------------------------------------------------------

class MarkReadBroadcastTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = _make_user("read.me@example.com", "Read Me")
        self.other = _make_user("read.other@example.com", "Read Other")
        access = str(RefreshToken.for_user(self.me).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        self.room = ChatRoom(
            room_id="read-room-01",
            name="Read room",
            participants=[str(self.me.pk), str(self.other.pk)],
        )
        self._patchers = [
            patch("chat.views.ChatRoom.get_by_room_id",
                  return_value=self.room),
            patch("chat.views.Message.mark_room_read", return_value=2),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

        self.mock_layer = MagicMock()
        self.mock_layer.group_send = AsyncMock()
        layer_patcher = patch(
            "chat.views.get_channel_layer", return_value=self.mock_layer
        )
        layer_patcher.start()
        self.addCleanup(layer_patcher.stop)

    def test_mark_read_broadcasts_chat_read_to_room(self):
        response = self.client.post("/api/chat/rooms/read-room-01/read/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["marked_read"], 2)
        self.mock_layer.group_send.assert_awaited_once_with(
            "chat_read-room-01",
            {
                "type": "chat.read",
                "room_id": "read-room-01",
                "reader_id": str(self.me.pk),
            },
        )

    def test_no_broadcast_when_nothing_newly_marked(self):
        with patch("chat.views.Message.mark_room_read", return_value=0):
            response = self.client.post("/api/chat/rooms/read-room-01/read/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["marked_read"], 0)
        self.mock_layer.group_send.assert_not_awaited()


# ---------------------------------------------------------------------------
# FIX 8 — rooms list: last_message + unread_count (batched)
# ---------------------------------------------------------------------------

class RoomListEnrichmentTests(MessageFakeCollectionMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.me = _make_user("inbox.me@example.com", "Inbox Me")
        self.other = _make_user("inbox.other@example.com", "Inbox Other")
        access = str(RefreshToken.for_user(self.me).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        self.rooms = [
            ChatRoom(room_id="inbox-room-1", name="Room 1",
                     participants=[str(self.me.pk), str(self.other.pk)]),
            ChatRoom(room_id="inbox-room-2", name="Room 2",
                     participants=[str(self.me.pk), str(self.other.pk)]),
            ChatRoom(room_id="inbox-room-3", name="Empty room",
                     participants=[str(self.me.pk), str(self.other.pk)]),
        ]
        patcher = patch(
            "chat.views.ChatRoom.get_for_user", return_value=self.rooms
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        me, other = str(self.me.pk), str(self.other.pk)
        # Room 1: two from other (one unread), then my own reply (newest).
        self._fake_messages.insert_one({
            "room_id": "inbox-room-1", "sender_id": other,
            "sender_username": "other", "content": "First",
            "message_type": "text", "read_by": [other],
            "created_at": _ts(10),
        })
        self._fake_messages.insert_one({
            "room_id": "inbox-room-1", "sender_id": other,
            "sender_username": "other", "content": "Second",
            "message_type": "text", "read_by": [other, me],
            "created_at": _ts(11),
        })
        self._fake_messages.insert_one({
            "room_id": "inbox-room-1", "sender_id": me,
            "sender_username": "me", "content": "My reply",
            "message_type": "text", "read_by": [me],
            "created_at": _ts(12),
        })
        # Room 2: one unread message from other.
        self._fake_messages.insert_one({
            "room_id": "inbox-room-2", "sender_id": other,
            "sender_username": "other", "content": "Hey there",
            "message_type": "text", "read_by": [other],
            "created_at": _ts(9),
        })
        # Room 3: no messages.

    def test_rooms_list_includes_last_message_and_unread_count(self):
        response = self.client.get("/api/chat/rooms/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 3)
        by_id = {item["room_id"]: item for item in response.data}

        room1 = by_id["inbox-room-1"]
        self.assertEqual(room1["last_message"]["content"], "My reply")
        self.assertEqual(room1["last_message"]["sender_id"], str(self.me.pk))
        self.assertEqual(room1["unread_count"], 1)

        room2 = by_id["inbox-room-2"]
        self.assertEqual(room2["last_message"]["content"], "Hey there")
        self.assertEqual(room2["unread_count"], 1)

        room3 = by_id["inbox-room-3"]
        self.assertIsNone(room3["last_message"])
        self.assertEqual(room3["unread_count"], 0)

    def test_enrichment_is_batched_not_per_room(self):
        """Three rooms must cost exactly two aggregations (one for last
        messages, one for unread counts) — not one query per room."""
        response = self.client.get("/api/chat/rooms/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._fake_messages.aggregate_calls, 2)

    def test_empty_room_list_skips_aggregation(self):
        with patch("chat.views.ChatRoom.get_for_user", return_value=[]):
            response = self.client.get("/api/chat/rooms/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
        self.assertEqual(self._fake_messages.aggregate_calls, 0)


class InboxBatchMethodTests(MessageFakeCollectionMixin, TestCase):
    """The batch helpers themselves: empty input, missing rooms."""

    def test_empty_room_list_returns_empty_without_querying(self):
        self.assertEqual(Message.last_messages_for_rooms([]), {})
        self.assertEqual(Message.unread_counts_for_rooms([], "1"), {})
        self.assertEqual(self._fake_messages.aggregate_calls, 0)

    def test_unread_counts_exclude_own_messages(self):
        self._fake_messages.insert_one({
            "room_id": "own-room", "sender_id": "1",
            "sender_username": "me", "content": "My own message",
            "message_type": "text", "read_by": ["1"],
            "created_at": _ts(10),
        })
        self.assertEqual(
            Message.unread_counts_for_rooms(["own-room"], "1"), {}
        )
        last = Message.last_messages_for_rooms(["own-room"])
        self.assertEqual(last["own-room"].content, "My own message")
