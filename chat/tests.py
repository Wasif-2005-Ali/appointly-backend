"""
chat/tests.py — WebSocket consumer tests for the chat app.

No MongoDB server is available in the test environment, so room lookups
are mocked (``ChatRoom.get_by_room_id`` patched on the consumer module).
The invalid-token test needs no MongoDB at all: auth fails first.
"""

from __future__ import annotations

from unittest import mock

from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from chat.routing import websocket_urlpatterns


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
