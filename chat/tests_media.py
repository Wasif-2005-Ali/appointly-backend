"""Tests for POST /api/chat/rooms/<room_id>/media/ (chat media upload).

MongoDB is not available in the test environment, so the Mongo-backed
class methods are patched: ``ChatRoom.get_by_room_id`` returns an
in-memory room and ``Message.send`` returns a Message built from its
kwargs. ``cloudinary.uploader.upload`` is mocked — no real upload
happens. The channel layer is mocked so the broadcast can be asserted
without a live WebSocket.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import User
from chat.models import ChatRoom, Message
from chat.views import MediaUploadView


CLOUDINARY_SETTINGS = {
    "CLOUDINARY_CLOUD_NAME": "test-cloud",
    "CLOUDINARY_API_KEY": "test-key",
    "CLOUDINARY_API_SECRET": "test-secret",
}

SECURE_URL = (
    "https://res.cloudinary.com/test-cloud/image/upload/"
    "v1/appointly/chat/media-room-01/pic.jpg"
)

ROOM_ID = "media-room-01"


def _fake_send(*, room_id, sender_id, sender_username, content,
               message_type="text", file_name=None, file_size=None):
    """Stand-in for Message.send: build the Message without touching Mongo."""
    return Message(
        room_id=room_id,
        sender_id=sender_id,
        sender_username=sender_username,
        content=content,
        message_type=message_type,
        file_name=file_name,
        file_size=file_size,
        read_by=[sender_id],
        _id=ObjectId(),
    )


@override_settings(**CLOUDINARY_SETTINGS)
class MediaUploadTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.me = User.objects.create_user(
            email="media.me@example.com",
            full_name="Media Me",
            profession="Student",
            password="SecurePass123!",
        )
        self.other = User.objects.create_user(
            email="media.other@example.com",
            full_name="Media Other",
            profession="Doctor",
            password="SecurePass123!",
        )
        self.outsider = User.objects.create_user(
            email="media.outsider@example.com",
            full_name="Media Outsider",
            profession="Engineer",
            password="SecurePass123!",
        )

        access = str(RefreshToken.for_user(self.me).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        self.room = ChatRoom(
            room_id=ROOM_ID,
            name="Media test room",
            participants=[str(self.me.pk), str(self.other.pk)],
        )
        self.url = f"/api/chat/rooms/{ROOM_ID}/media/"

        # Patch the Mongo-backed lookups and the external services.
        self._patchers = [
            patch("chat.views.ChatRoom.get_by_room_id",
                  return_value=self.room),
            patch("chat.views.Message.send", side_effect=_fake_send),
            patch("cloudinary.uploader.upload",
                  return_value={"secure_url": SECURE_URL}),
        ]
        self.mock_get_room, self.mock_send, self.mock_upload = [
            p.start() for p in self._patchers
        ]
        for p in self._patchers:
            self.addCleanup(p.stop)

        self.mock_layer = MagicMock()
        self.mock_layer.group_send = AsyncMock()
        layer_patcher = patch(
            "chat.views.get_channel_layer", return_value=self.mock_layer
        )
        layer_patcher.start()
        self.addCleanup(layer_patcher.stop)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _upload(self, name="pic.jpg", content=b"fake-image-bytes",
                content_type="image/jpeg"):
        f = SimpleUploadedFile(name, content, content_type=content_type)
        return self.client.post(self.url, {"file": f}, format="multipart")

    def _assert_broadcast(self, message_type):
        self.mock_layer.group_send.assert_awaited_once()
        group, event = self.mock_layer.group_send.await_args.args
        self.assertEqual(group, f"chat_{ROOM_ID}")
        self.assertEqual(event["type"], "chat.message")
        self.assertEqual(event["message"]["message_type"], message_type)
        self.assertEqual(event["message"]["content"], SECURE_URL)

    # ------------------------------------------------------------------
    # Success cases
    # ------------------------------------------------------------------

    def test_upload_image_success(self):
        response = self._upload()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["room_id"], ROOM_ID)
        self.assertEqual(data["sender_id"], str(self.me.pk))
        self.assertEqual(data["sender_username"], self.me.email)
        self.assertEqual(data["content"], SECURE_URL)
        self.assertEqual(data["message_type"], "image")
        self.assertEqual(data["file_name"], "pic.jpg")
        self.assertEqual(data["file_size"], len(b"fake-image-bytes"))
        self.assertEqual(data["read_by"], [str(self.me.pk)])
        self.assertTrue(data["id"])
        self.assertTrue(data["created_at"])

        # Cloudinary received the file in the per-room folder, auto type.
        self.mock_upload.assert_called_once()
        _, kwargs = self.mock_upload.call_args
        self.assertEqual(kwargs["folder"], f"appointly/chat/{ROOM_ID}")
        self.assertEqual(kwargs["resource_type"], "auto")

        self._assert_broadcast("image")

    def test_upload_file_success(self):
        response = self._upload(
            name="notes.pdf",
            content=b"%PDF-fake",
            content_type="application/pdf",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["message_type"], "file")
        self.assertEqual(data["file_name"], "notes.pdf")
        self.assertEqual(data["file_size"], len(b"%PDF-fake"))
        self.assertEqual(data["content"], SECURE_URL)

        self._assert_broadcast("file")

    # ------------------------------------------------------------------
    # Auth / membership / room errors
    # ------------------------------------------------------------------

    def test_upload_requires_auth(self):
        self.client.credentials()  # drop the Bearer token
        response = self._upload()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.mock_upload.assert_not_called()

    def test_non_member_gets_403(self):
        access = str(RefreshToken.for_user(self.outsider).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self._upload()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.mock_upload.assert_not_called()

    def test_unknown_room_gets_404(self):
        self.mock_get_room.return_value = None
        response = self.client.post(
            "/api/chat/rooms/no-such-room/media/",
            {"file": SimpleUploadedFile(
                "pic.jpg", b"fake-image-bytes", content_type="image/jpeg")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.mock_upload.assert_not_called()

    # ------------------------------------------------------------------
    # Validation errors
    # ------------------------------------------------------------------

    def test_missing_file_gets_400(self):
        response = self.client.post(self.url, {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_upload.assert_not_called()

    def test_oversized_image_gets_400(self):
        response = self._upload(
            content=b"x" * (MediaUploadView.MAX_IMAGE_BYTES + 1),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_upload.assert_not_called()

    def test_oversized_file_gets_400(self):
        response = self._upload(
            name="big.pdf",
            content=b"x" * (MediaUploadView.MAX_FILE_BYTES + 1),
            content_type="application/pdf",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_upload.assert_not_called()

    # ------------------------------------------------------------------
    # Configuration error
    # ------------------------------------------------------------------

    @override_settings(
        CLOUDINARY_CLOUD_NAME="",
        CLOUDINARY_API_KEY="",
        CLOUDINARY_API_SECRET="",
    )
    def test_unconfigured_cloudinary_gets_503(self):
        response = self._upload()
        self.assertEqual(
            response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE
        )
        self.mock_upload.assert_not_called()
