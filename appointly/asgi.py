"""
ASGI config for appointly project.

Wraps Django's HTTP ASGI application with Django Channels so that
WebSocket connections are dispatched to the correct consumer while
standard HTTP requests continue to flow through Django's view layer.

Protocol routing
----------------
  http       → Django views / DRF
  websocket  → Combined URL patterns for Chat and Call (WebRTC signaling)
               Guarded by AllowedHostsOriginValidator for CSWSH protection.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'appointly.settings')

# Initialise Django early so the app registry is ready before any
# app-specific imports (e.g. consumers importing models).
django_asgi_app = get_asgi_application()

# Import routing only after Django is set up.
from chat.routing import websocket_urlpatterns as chat_ws_urlpatterns  # noqa: E402
from call.routing import websocket_urlpatterns as call_ws_urlpatterns  # noqa: E402

websocket_urlpatterns = chat_ws_urlpatterns + call_ws_urlpatterns

application = ProtocolTypeRouter({
    # Standard HTTP → Django views / DRF
    "http": django_asgi_app,

    # WebSocket → JWT-authenticated chat and WebRTC call consumers
    "websocket": AllowedHostsOriginValidator(
        URLRouter(websocket_urlpatterns)
    ),
})
