"""
chat/urls.py — URL patterns for the chat REST API.

Mounted at /api/chat/ by the root URLconf (appointly/urls.py).
"""

from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    # Rooms
    path(
        "rooms/",
        views.RoomListCreateView.as_view(),
        name="room-list-create",
    ),
    path(
        "rooms/<str:room_id>/",
        views.RoomDetailView.as_view(),
        name="room-detail",
    ),

    # Participant management
    path(
        "rooms/<str:room_id>/participants/add/",
        views.AddParticipantView.as_view(),
        name="room-add-participant",
    ),
    path(
        "rooms/<str:room_id>/participants/remove/",
        views.RemoveParticipantView.as_view(),
        name="room-remove-participant",
    ),

    # Messages
    path(
        "rooms/<str:room_id>/messages/",
        views.MessageListView.as_view(),
        name="message-list",
    ),
]
