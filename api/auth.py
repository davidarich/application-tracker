"""Who an API request is from: the user of the OAuth 2.0 access token it sends
(RFC 6750 bearer tokens; the token endpoint is api/routers/oauth.py)."""

from typing import cast, final, override

from django.http import HttpRequest
from ninja.errors import HttpError
from ninja.security import HttpBearer

from accounts.api_tokens import TOKEN_STARTS, Kind, user_for_access_token
from accounts.models import User

TOKEN_URL = "/api/v1/oauth/token"


@final
class TokenAuth(HttpBearer):
    """`Authorization: Bearer at_...` with an access token from the token endpoint."""

    @override
    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        return user_for_access_token(token)


def api_user(request: HttpRequest) -> User:
    """The user a request was authenticated as (TokenAuth sets request.auth)."""
    user = cast(object, getattr(request, "auth", None))
    if not isinstance(user, User):
        raise TypeError("api_user() needs a request authenticated by TokenAuth.")
    return user


def require_staff(request: HttpRequest) -> User:
    """The request's user, who must be staff (else 403)."""
    user = api_user(request)
    if not user.is_staff:
        raise HttpError(403, "Only staff can add or change skills.")
    return user


def refusal(request: HttpRequest) -> tuple[str, str]:
    """Why a request wasn't authenticated: (a message for the JSON body, the
    WWW-Authenticate header RFC 6750 asks a 401 to carry)."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return (
            "An access token is required: send Authorization: Bearer <access token>.",
            'Bearer realm="api"',
        )
    if token.startswith(TOKEN_STARTS[Kind.REFRESH]):
        message = (
            "That's a refresh token. Exchange it at "
            + TOKEN_URL
            + " for an access token, and send that instead."
        )
    else:
        message = (
            "The access token isn't valid or has expired. Get a new one at "
            + TOKEN_URL
            + " with your refresh token."
        )
    return (
        message,
        f'Bearer realm="api", error="invalid_token", error_description="{message}"',
    )
