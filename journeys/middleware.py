"""JWT authentication middleware for Django Channels WebSocket connections.

Reads the ``token`` query parameter, validates it with SimpleJWT, and attaches
the authenticated user to ``scope['user']``. Unauthenticated connections remain
as ``AnonymousUser`` — individual consumers are responsible for closing them.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user(token_key):
    from rest_framework_simplejwt.tokens import UntypedToken
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    from rest_framework_simplejwt.authentication import JWTAuthentication
    try:
        UntypedToken(token_key)
    except (InvalidToken, TokenError):
        return AnonymousUser()
    auth = JWTAuthentication()
    validated = auth.get_validated_token(token_key.encode())
    return auth.get_user(validated)


class JWTAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        qs = parse_qs(scope.get('query_string', b'').decode())
        token_list = qs.get('token', [])
        if token_list:
            scope['user'] = await _get_user(token_list[0])
        else:
            scope['user'] = AnonymousUser()
        return await self.inner(scope, receive, send)
