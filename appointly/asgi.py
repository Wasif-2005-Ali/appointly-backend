"""
ASGI config for appointly project.

Wraps Django's HTTP ASGI application with Django Channels so that
WebSocket connections are dispatched to the correct consumer while
standard HTTP requests continue to flow through Django's view layer.

Protocol routing
----------------
  http       → Django views / DRF
  websocket  → Combined URL patterns for Chat and Call (WebRTC signaling)
               Guarded by NativeClientOriginValidator (see below).

Origin validation
-----------------
  Browsers send an Origin header on the WebSocket handshake, and it is
  validated against ALLOWED_HOSTS (CSWSH protection). Native clients
  (the Flutter app's Dart WebSocket client) send NO Origin header at
  all, so a missing Origin must be allowed — authentication is the JWT
  ``?token=`` query param checked by each consumer, not the Origin.
  Channels' stock AllowedHostsOriginValidator rejects Origin-less
  handshakes with HTTP 403, which made every WebSocket from the phone
  fail (chat, notify and call alike).

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.conf import settings
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'appointly.settings')

# Initialise Django early so the app registry is ready before any
# app-specific imports (e.g. consumers importing models).
django_asgi_app = get_asgi_application()

# Import routing only after Django is set up.
from chat.routing import websocket_urlpatterns as chat_ws_urlpatterns  # noqa: E402
from call.routing import websocket_urlpatterns as call_ws_urlpatterns  # noqa: E402

websocket_urlpatterns = chat_ws_urlpatterns + call_ws_urlpatterns


class NativeClientOriginValidator(OriginValidator):
    """
    OriginValidator that allows a MISSING Origin header.

    Channels' stock validator rejects handshakes with no Origin
    (``valid_origin(None)`` is False unless ``"*"`` is allowed).
    Browsers always send Origin, so that is the right default for the
    web — but native clients do not: Dart's WebSocket client sends no
    Origin header at all, so the stock validator 403s every connection
    from the Flutter app.

    Authentication here is the JWT ``?token=`` query param checked by
    each consumer, not the Origin header, so a missing Origin is not a
    security hole. When an Origin IS present it is still validated
    against the allowed list exactly like the stock validator, keeping
    CSWSH protection for browser clients.
    """

    def valid_origin(self, parsed_origin):
        if parsed_origin is None:
            # No Origin header — a native client (or a non-browser
            # tool). Allow; the consumer still requires a valid JWT.
            return True
        return super().valid_origin(parsed_origin)


def AllowedHostsOriginValidatorAllowingNativeClients(application):
    """
    Factory mirroring channels' ``AllowedHostsOriginValidator``, but
    wrapping :class:`NativeClientOriginValidator`: allowed hosts come
    from settings.ALLOWED_HOSTS, and a missing Origin is allowed.
    """
    allowed_hosts = settings.ALLOWED_HOSTS
    if settings.DEBUG and not allowed_hosts:
        allowed_hosts = ["localhost", "127.0.0.1", "[::1]"]
    return NativeClientOriginValidator(application, allowed_hosts)


application = ProtocolTypeRouter({
    # Standard HTTP → Django views / DRF
    "http": django_asgi_app,

    # WebSocket → JWT-authenticated chat and WebRTC call consumers.
    # Missing Origin allowed (native clients); a present Origin is
    # still validated against ALLOWED_HOSTS.
    "websocket": AllowedHostsOriginValidatorAllowingNativeClients(
        URLRouter(websocket_urlpatterns)
    ),
})
