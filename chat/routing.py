"""
chat/routing.py — WebSocket URL patterns for the chat app.

Imported by appointly/asgi.py and plugged into the ProtocolTypeRouter.
"""

from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    # ws://host/ws/chat/<room_id>/
    # room_id is a 12-character hex slug (see ChatRoom._new_room_id)
    re_path(
        r"^ws/chat/(?P<room_id>[0-9a-f]{12})/$",
        consumers.ChatConsumer.as_asgi(),
        name="ws-chat",
    ),
]
