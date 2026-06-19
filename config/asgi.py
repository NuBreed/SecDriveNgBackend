"""ASGI entry point — wraps Django with Django Channels for WebSocket support."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Import order matters: get_asgi_application() first so Django is fully
# initialised before anything else imports models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

from journeys.middleware import JWTAuthMiddleware
from journeys.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        JWTAuthMiddleware(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
