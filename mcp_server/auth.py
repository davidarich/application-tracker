"""Who an MCP request is from: the user of the OAuth 2.0 access token it
sends, which must be from an MCP grant (accounts/oauth.py); a JSON API
token is refused, as the MCP spec asks."""

from typing import cast, final

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import connections
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from accounts.api_tokens import Audience, live_access_token
from accounts.models import User


def tidy_connections() -> None:
    """Close database connections that are broken or past CONN_MAX_AGE, as
    Django does around each request (it can't here: these aren't Django
    requests). A connection inside a transaction, as in tests, is kept."""
    for connection in connections.all(initialized_only=True):
        if not connection.in_atomic_block:
            connection.close_if_unusable_or_obsolete()


def access_token_for(token: str) -> AccessToken | None:
    """The SDK's view of a live MCP access token, or None."""
    tidy_connections()
    record = live_access_token(token, Audience.MCP)
    if record is None:
        return None
    grant = record.grant
    return AccessToken(
        token=token,
        client_id=grant.client.client_id if grant.client else str(grant.id),
        scopes=[],
        expires_at=int(record.expires_at.timestamp()),
        resource=cast(str, settings.MCP_RESOURCE_URL),
        subject=str(grant.user.id),
    )


@final
class GrantTokenVerifier:
    """The SDK's TokenVerifier for our access tokens (accounts/api_tokens.py)."""

    async def verify_token(self, token: str) -> AccessToken | None:
        return await sync_to_async(access_token_for, thread_sensitive=True)(token)


def request_subject() -> str | None:
    """The user ID of the current request's access token (call this in the
    request's async code: it reads a context variable the SDK sets)."""
    token = get_access_token()
    return token.subject if token is not None else None


def user_for_subject(subject: str | None) -> User | None:
    """The active user with this ID, or None."""
    if not subject:
        return None
    return User.objects.filter(pk=subject, is_active=True).first()
