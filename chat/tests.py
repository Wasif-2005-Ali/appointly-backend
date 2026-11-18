"""
chat/tests.py — WebSocket consumer tests for the chat app.

No MongoDB server is available in the test environment, so room lookups
are mocked (``ChatRoom.get_by_room_id`` patched on the consumer module).
The invalid-token test needs no MongoDB at all: auth fails first.
"""

from __future__ import annotations

from unittest import mock

from bson import ObjectId
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from appointly.asgi import application as asgi_application
from chat.models import Message
from chat.routing import websocket_urlpatterns


def _fake_send_with_reply(*, room_id, sender_id, sender_username, content,
                          message_type="text", file_name=None, file_size=None,
                          reply_to_id=None, reply_to_text=None):
    """Stand-in for Message.send: build the Message without touching Mongo."""
    return Message(
        room_id=room_id,
        sender_id=sender_id,
        sender_username=sender_username,
        content=content,
        message_type=message_type,
        file_name=file_name,
        file_size=file_size,
        reply_to_id=reply_to_id,
        reply_to_text=reply_to_text,
        read_by=[sender_id],
        _id=ObjectId(),
    )


class ChatConsumerCloseCodeTests(TransactionTestCase):
    """Close codes must reach the client (accept-then-close).

    Previously the consumer closed BEFORE accept, so Daphne turned
    4001/4003/4004 into an HTTP 403 at handshake and the client never
    saw the code — it burned all reconnect attempts on a dead token.
    """

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            email="chatter@test.com", full_name="Chatter",
            profession="Tester", password="TestPass123!",
        )
        self.application = URLRouter(websocket_urlpatterns)
        self._token = str(RefreshToken.for_user(self.user).access_token)

    def _communicator(self, room_id, token=None):
        # The URL is built by concatenation on purpose: writing the
        # token into the query string by interpolation gets mangled
        # when the file is saved.
        if token is None:
            token = self._token
        return WebsocketCommunicator(
            self.application,
            "/ws/chat/" + room_id + "/?token=" + token,
        )

    async def _expect_close_code(self, communicator, code):
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        close = await communicator.receive_output(timeout=5)
        self.assertEqual(close["type"], "websocket.close")
        self.assertEqual(close["code"], code)
        await communicator.wait(timeout=5)

    async def test_invalid_token_close_code_reaches_client(self):
        comm = self._communicator("aabbccddeeff", token="not-a-real-token")
        await self._expect_close_code(comm, 4001)

    async def test_missing_room_close_code_reaches_client(self):
        with mock.patch(
            "chat.consumers.ChatRoom.get_by_room_id", return_value=None
        ):
            comm = self._communicator("aabbccddeeff")
            await self._expect_close_code(comm, 4004)

    async def test_non_member_close_code_reaches_client(self):
        room = mock.Mock(participants=["999"])
        with mock.patch(
            "chat.consumers.ChatRoom.get_by_room_id", return_value=room
        ):
            comm = self._communicator("aabbccddeeff")
            await self._expect_close_code(comm, 4003)


class OriginValidatorTests(TransactionTestCase):
    """FIX 1: the ASGI Origin validator must allow a MISSING Origin.

    Dart's WebSocket client sends no Origin header, so Channels' stock
    AllowedHostsOriginValidator 403'd every handshake from the phone.
    The app's NativeClientOriginValidator allows a missing Origin but
    still validates a present one against ALLOWED_HOSTS (CSWSH
    protection for browsers). These tests run against the REAL ASGI
    application (appointly.asgi:application), not the bare URLRouter.
    """

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            email="origin@test.com", full_name="Origin",
            profession="Tester", password="TestPass123!",
        )
        self._token = str(RefreshToken.for_user(self.user).access_token)
        self.room = mock.Mock(participants=[str(self.user.pk)])

    def _communicator(self, headers):
        return WebsocketCommunicator(
            asgi_application,
            "/ws/chat/aabbccddeeff/?token=" + self._token,
            headers=headers,
        )

    async def test_handshake_without_origin_succeeds(self):
        """A native client sends no Origin — the handshake must pass."""
        with mock.patch(
            "chat.consumers.ChatRoom.get_by_room_id", return_value=self.room
        ):
            comm = self._communicator([(b"host", b"testserver")])
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            await comm.disconnect()

    async def test_handshake_with_good_origin_succeeds(self):
        """A browser from an allowed host still passes."""
        with mock.patch(
            "chat.consumers.ChatRoom.get_by_room_id", return_value=self.room
        ):
            comm = self._communicator([
                (b"host", b"testserver"),
                (b"origin", b"http://testserver"),
            ])
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            await comm.disconnect()

    async def test_handshake_with_bad_origin_is_rejected(self):
        """CSWSH protection stays: a foreign Origin is still denied."""
        with mock.patch(
            "chat.consumers.ChatRoom.get_by_room_id", return_value=self.room
        ):
            comm = self._communicator([
                (b"host", b"testserver"),
                (b"origin", b"https://evil.example.com"),
            ])
            connected, _ = await comm.connect()
            self.assertFalse(connected)
            await comm.wait(timeout=5)


class ChatConsumerReplyTests(TransactionTestCase):
    """FIX 6: reply quotes (reply_to_id / reply_to_text) reach the room."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            email="replier@test.com", full_name="Replier",
            profession="Tester", password="TestPass123!",
        )
        self.application = URLRouter(websocket_urlpatterns)
        self._token = str(RefreshToken.for_user(self.user).access_token)
        self.room = mock.Mock(participants=[str(self.user.pk)])

    def _communicator(self):
        return WebsocketCommunicator(
            self.application,
            "/ws/chat/aabbccddeeff/?token=" + self._token,
        )

    async def test_reply_fields_are_broadcast(self):
        with (
            mock.patch(
                "chat.consumers.ChatRoom.get_by_room_id",
                return_value=self.room,
            ),
            mock.patch.object(
                Message, "send", side_effect=_fake_send_with_reply
            ),
        ):
            comm = self._communicator()
            connected, _ = await comm.connect()
            self.assertTrue(connected)

            await comm.send_json_to({
                "type": "chat.message",
                "content": "Agreed!",
                "reply_to_id": "507f1f77bcf86cd799439011",
                "reply_to_text": "Shall we meet at 5?",
            })
            frame = await comm.receive_json_from(timeout=5)
            self.assertEqual(frame["type"], "chat.message")
            self.assertEqual(
                frame["message"]["reply_to_id"],
                "507f1f77bcf86cd799439011",
            )
            self.assertEqual(
                frame["message"]["reply_to_text"], "Shall we meet at 5?"
            )
            await comm.disconnect()

    async def test_plain_message_has_null_reply_fields(self):
        with (
            mock.patch(
                "chat.consumers.ChatRoom.get_by_room_id",
                return_value=self.room,
            ),
            mock.patch.object(
                Message, "send", side_effect=_fake_send_with_reply
            ),
        ):
            comm = self._communicator()
            connected, _ = await comm.connect()
            self.assertTrue(connected)

            await comm.send_json_to({
                "type": "chat.message",
                "content": "Hello, no quote here.",
            })
            frame = await comm.receive_json_from(timeout=5)
            self.assertIsNone(frame["message"]["reply_to_id"])
            self.assertIsNone(frame["message"]["reply_to_text"])
            await comm.disconnect()


class ChatReadHandlerTests(TransactionTestCase):
    """FIX 7: the ``chat.read`` group event reaches room members."""

    def setUp(self):
        user_model = get_user_model()
        self.me = user_model.objects.create_user(
            email="reader@test.com", full_name="Reader",
            profession="Tester", password="TestPass123!",
        )
        self.peer = user_model.objects.create_user(
            email="sender@test.com", full_name="Sender",
            profession="Tester", password="TestPass123!",
        )
        self.application = URLRouter(websocket_urlpatterns)
        self._tokens = {
            str(u.pk): str(RefreshToken.for_user(u).access_token)
            for u in (self.me, self.peer)
        }
        self.room = mock.Mock(
            participants=[str(self.me.pk), str(self.peer.pk)]
        )

    def _communicator(self, user):
        return WebsocketCommunicator(
            self.application,
            "/ws/chat/aabbccddeeff/?token=" + self._tokens[str(user.pk)],
        )

    async def test_chat_read_event_is_forwarded_to_room(self):
        with mock.patch(
            "chat.consumers.ChatRoom.get_by_room_id", return_value=self.room
        ):
            comm_me = self._communicator(self.me)
            comm_peer = self._communicator(self.peer)
            connected, _ = await comm_me.connect()
            self.assertTrue(connected)
            connected, _ = await comm_peer.connect()
            self.assertTrue(connected)

            # Simulate what MarkReadView does after marking read.
            await get_channel_layer().group_send(
                "chat_aabbccddeeff",
                {
                    "type": "chat.read",
                    "room_id": "aabbccddeeff",
                    "reader_id": str(self.me.pk),
                },
            )

            frame = await comm_peer.receive_json_from(timeout=5)
            self.assertEqual(frame["type"], "chat.read")
            self.assertEqual(frame["room_id"], "aabbccddeeff")
            self.assertEqual(frame["reader_id"], str(self.me.pk))

            await comm_me.disconnect()
            await comm_peer.disconnect()
