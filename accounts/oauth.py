"""The OAuth 2.0 authorization server that lets AI agent apps connect to the
MCP server (mcp_server/): the authorization code grant with PKCE, as the MCP
spec's authorization section asks (OAuth 2.1).

1. The app registers itself (dynamic client registration, RFC 7591) at
   POST /api/v1/oauth/register and gets a client_id. Clients are public:
   there's no secret, so anyone can register one, and its name is unverified.
2. It sends the user's browser to /oauth/authorize/ (accounts/views.py) with
   its client_id, redirect_uri, state, a PKCE code_challenge (S256 only) and
   the MCP server's URL as `resource` (RFC 8707). The user logs in and allows
   it on the consent page, which redirects back with a one-time code (and
   `iss`, RFC 9207). Errors before the redirect URI is known to be the
   client's are shown on a page, never redirected.
3. The app swaps the code, with its code_verifier, at the token endpoint
   (api/routers/oauth.py) for the first tokens of a new MCP grant (an
   ApiGrant with audience "mcp"), then refreshes them like any grant's.

The web app's origin is the issuer (settings.OAUTH_ISSUER); it publishes
these endpoints at /.well-known/oauth-authorization-server (RFC 8414). The
MCP server points clients here from its own protected resource metadata.
"""

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast, final
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .api_tokens import TokenPair, end_grant, hash_token, issue_mcp_grant
from .models import AuthorizationCode, OAuthClient, User

CODE_START = "ac_"
PREFIX_LENGTH = 12
CODE_LIFETIME = timedelta(minutes=5)
# A registered client that never gets a grant is deleted after this long.
UNUSED_CLIENT_LIFETIME = timedelta(days=1)
MAX_REDIRECT_URIS = 10
MAX_URI_LENGTH = 2000
MAX_NAME_LENGTH = 100
DEFAULT_CLIENT_NAME = "Unnamed app"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# RFC 7636 section 4.1: 43 to 128 unreserved characters.
VERIFIER_RE = re.compile(r"[A-Za-z0-9._~-]{43,128}")
# base64url (no padding) of a SHA-256 hash: 43 characters.
CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{43}")

TOKEN_PATH = "/api/v1/oauth/token"
REGISTRATION_PATH = "/api/v1/oauth/register"


@final
class OAuthError(Exception):
    """An OAuth error: `error` is the RFC's code (e.g. "invalid_grant"),
    `description` says what went wrong in words."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description


@final
class RedirectError(Exception):
    """An authorization request error to send back to the client, at its
    (checked) redirect URI (RFC 6749 section 4.1.2.1)."""

    def __init__(self, request: "AuthorizeRequest", error: str, description: str):
        super().__init__(f"{error}: {description}")
        self.request = request
        self.error = error
        self.description = description

    def redirect_url(self) -> str:
        return self.request.redirect_with(
            {"error": self.error, "error_description": self.description}
        )


def issuer() -> str:
    return cast(str, settings.OAUTH_ISSUER)


def mcp_resource() -> str:
    return cast(str, settings.MCP_RESOURCE_URL)


def same_resource(given: str, expected: str) -> bool:
    """Whether a `resource` names `expected`; a trailing slash doesn't matter."""
    return given.rstrip("/") == expected.rstrip("/")


def server_metadata() -> dict[str, object]:
    """The authorization server metadata (RFC 8414)."""
    base = issuer()
    return {
        "issuer": base,
        "authorization_endpoint": base + reverse("accounts:oauth_authorize"),
        "token_endpoint": base + TOKEN_PATH,
        "registration_endpoint": base + REGISTRATION_PATH,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "authorization_response_iss_parameter_supported": True,
    }


# --- Registration ------------------------------------------------------------------


def is_loopback(parts: SplitResult) -> bool:
    return parts.scheme == "http" and (parts.hostname or "") in LOOPBACK_HOSTS


def redirect_uri_problem(uri: str) -> str | None:
    """Why `uri` can't be a redirect URI, or None if it can: it must be
    https, or http on this computer (localhost, 127.0.0.1 or [::1], for apps
    that listen locally, RFC 8252), with no #fragment."""
    if len(uri) > MAX_URI_LENGTH:
        return f"Redirect URIs can be at most {MAX_URI_LENGTH} characters."
    try:
        parts = urlsplit(uri)
        _ = parts.port  # raises ValueError for a bad port
    except ValueError:
        return f"{uri} isn't a valid URL."
    if parts.fragment or "#" in uri:
        return "Redirect URIs can't have a #fragment."
    if parts.scheme == "https" and parts.hostname:
        return None
    if is_loopback(parts):
        return None
    return f"{uri} must use https, or http on localhost."


def strings(value: object) -> list[str] | None:
    """`value` if it's a list of strings, else None."""
    if not isinstance(value, list):
        return None
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        return None
    return cast(list[str], items)


def register_client(metadata: Mapping[str, object]) -> OAuthClient:
    """Register a client from its RFC 7591 metadata. Only public clients
    using the authorization code grant are supported: other values the client
    asks for are replaced, as the RFC allows, and the answer says so."""
    uris = strings(metadata.get("redirect_uris"))
    if not uris:
        raise OAuthError("invalid_redirect_uri", "Give redirect_uris: a list of URLs.")
    if len(uris) > MAX_REDIRECT_URIS:
        raise OAuthError(
            "invalid_redirect_uri",
            f"Give at most {MAX_REDIRECT_URIS} redirect URIs.",
        )
    for uri in uris:
        if problem := redirect_uri_problem(uri):
            raise OAuthError("invalid_redirect_uri", problem)
    grant_types = strings(metadata.get("grant_types", ["authorization_code"]))
    if grant_types is None or "authorization_code" not in grant_types:
        raise OAuthError(
            "invalid_client_metadata",
            "Only the authorization_code grant (with refresh_token) is supported.",
        )
    response_types = strings(metadata.get("response_types", ["code"]))
    if response_types is None or "code" not in response_types:
        raise OAuthError(
            "invalid_client_metadata", 'Only the "code" response type is supported.'
        )
    name = metadata.get("client_name", "")
    if not isinstance(name, str):
        raise OAuthError("invalid_client_metadata", "client_name must be a string.")
    name = " ".join(name.split())[:MAX_NAME_LENGTH] or DEFAULT_CLIENT_NAME

    now = timezone.now()
    # Tidy up: clients registered a while ago that were never allowed in.
    _ = OAuthClient.objects.filter(
        created_at__lt=now - UNUSED_CLIENT_LIFETIME, grants__isnull=True
    ).delete()
    return OAuthClient.objects.create(
        client_id=secrets.token_urlsafe(24),
        name=name,
        redirect_uris=list(dict.fromkeys(uris)),
    )


def client_information(client: OAuthClient) -> dict[str, object]:
    """The registration response (RFC 7591 section 3.2.1)."""
    return {
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "client_name": client.name,
        "redirect_uris": client.redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


# --- Authorization -----------------------------------------------------------------


def redirect_uri_matches(registered: list[str], uri: str) -> bool:
    """Whether `uri` is one of the client's redirect URIs: exactly, except
    that a loopback URI may use any port (RFC 8252 section 7.3)."""
    if uri in registered:
        return True
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if not is_loopback(parts):
        return False
    for candidate in registered:
        known = urlsplit(candidate)
        if (
            is_loopback(known)
            and known.hostname == parts.hostname
            and known.path == parts.path
            and known.query == parts.query
            and not parts.fragment
        ):
            return True
    return False


@dataclass(frozen=True)
class AuthorizeRequest:
    """A checked authorization request, as the consent page shows it."""

    client: OAuthClient
    redirect_uri: str
    state: str
    code_challenge: str
    resource: str

    @property
    def redirect_host(self) -> str:
        return urlsplit(self.redirect_uri).netloc

    def redirect_with(self, params: dict[str, str]) -> str:
        """The redirect URI with `params`, the state and the issuer added to
        its query."""
        parts = urlsplit(self.redirect_uri)
        query = parse_qsl(parts.query, keep_blank_values=True)
        extra = {**params, "iss": issuer()}
        if self.state:
            extra["state"] = self.state
        query.extend(extra.items())
        return urlunsplit(parts._replace(query=urlencode(query)))

    def hidden_fields(self) -> dict[str, str]:
        """The parameters the consent form sends back, to check again."""
        return {
            "response_type": "code",
            "client_id": self.client.client_id,
            "redirect_uri": self.redirect_uri,
            "state": self.state,
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "resource": self.resource,
        }


def parse_authorize(params: Mapping[str, str]) -> AuthorizeRequest:
    """Check an authorization request's parameters.

    Raises OAuthError if the client or redirect URI is wrong (shown to the
    user, never redirected), or RedirectError for other mistakes (sent back
    to the client).
    """
    client_id = params.get("client_id", "")
    client = (
        OAuthClient.objects.filter(client_id=client_id).first() if client_id else None
    )
    if client is None:
        raise OAuthError(
            "invalid_client",
            "The app connecting isn't registered (or its registration expired).",
        )
    redirect_uri = params.get("redirect_uri", "")
    if not redirect_uri:
        raise OAuthError(
            "invalid_request", "The app didn't say where to send you back."
        )
    if not redirect_uri_matches(client.redirect_uris, redirect_uri):
        raise OAuthError(
            "invalid_request",
            "The app asked to send you back to an address it didn't register.",
        )
    resource = params.get("resource", "").strip() or mcp_resource()
    request = AuthorizeRequest(
        client=client,
        redirect_uri=redirect_uri,
        state=params.get("state", ""),
        code_challenge=params.get("code_challenge", ""),
        resource=resource,
    )
    if params.get("response_type") != "code":
        raise RedirectError(
            request, "unsupported_response_type", 'response_type must be "code".'
        )
    if not request.code_challenge:
        raise RedirectError(
            request, "invalid_request", "code_challenge is required (PKCE)."
        )
    if params.get("code_challenge_method") != "S256":
        raise RedirectError(
            request, "invalid_request", 'code_challenge_method must be "S256".'
        )
    if not CHALLENGE_RE.fullmatch(request.code_challenge):
        raise RedirectError(
            request,
            "invalid_request",
            "code_challenge must be the base64url SHA-256 of the code verifier.",
        )
    if not same_resource(resource, mcp_resource()):
        raise RedirectError(
            request, "invalid_target", f"resource must be {mcp_resource()}."
        )
    return request


def issue_code(user: User, request: AuthorizeRequest) -> str:
    """A one-time authorization code for `user`, after they allowed `request`."""
    now = timezone.now()
    # Tidy up: expired codes are no use.
    _ = AuthorizationCode.objects.filter(expires_at__lte=now).delete()
    while True:
        code = CODE_START + secrets.token_urlsafe(32)
        prefix = code[:PREFIX_LENGTH]
        if not AuthorizationCode.objects.filter(prefix=prefix).exists():
            break
    _ = AuthorizationCode.objects.create(
        client=request.client,
        user=user,
        prefix=prefix,
        key_hash=hash_token(code),
        redirect_uri=request.redirect_uri,
        code_challenge=request.code_challenge,
        resource=request.resource,
        expires_at=now + CODE_LIFETIME,
    )
    return code


# --- Token exchange ----------------------------------------------------------------


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def find_code(code: str) -> AuthorizationCode | None:
    if not code.startswith(CODE_START) or len(code) <= PREFIX_LENGTH:
        return None
    record = (
        AuthorizationCode.objects.filter(prefix=code[:PREFIX_LENGTH])
        .select_related("client", "user", "grant")
        .first()
    )
    if record is None or not hmac.compare_digest(record.key_hash, hash_token(code)):
        return None
    return record


@dataclass(frozen=True)
class CodeExchange:
    code: str
    client_id: str
    redirect_uri: str
    code_verifier: str
    resource: str = ""


def exchange_code(exchange: CodeExchange) -> TokenPair:
    """Swap an authorization code for a new MCP grant's first tokens.

    Raises OAuthError if anything doesn't match. A code works once: sending
    it again revokes the grant it was swapped for, in case it was copied.
    """
    now = timezone.now()
    with transaction.atomic():
        outcome = _exchange(exchange, now)
    if isinstance(outcome, OAuthError):
        raise outcome
    return outcome


def _exchange(exchange: CodeExchange, now: datetime) -> TokenPair | OAuthError:
    """exchange_code()'s work, in its transaction; returns the error instead
    of raising, so revoking a reused code's grant is kept."""
    record = find_code(exchange.code)
    if record is None:
        return OAuthError("invalid_grant", "The authorization code isn't valid.")
    if exchange.client_id != record.client.client_id:
        return OAuthError(
            "invalid_grant", "The authorization code was issued to another client."
        )
    if record.expires_at <= now:
        return OAuthError("invalid_grant", "The authorization code has expired.")
    # Claim the code; only one request can. Any mistake below spends it too.
    claimed = AuthorizationCode.objects.filter(
        id=record.id, used_at__isnull=True
    ).update(used_at=now)
    if not claimed:
        if record.grant is not None:
            end_grant(record.grant)
        return OAuthError(
            "invalid_grant",
            "The authorization code was already used, so it may have been copied. "
            + "The access it gave has been revoked.",
        )
    if exchange.redirect_uri != record.redirect_uri:
        return OAuthError(
            "invalid_grant",
            "redirect_uri must be the one sent in the authorization request.",
        )
    if not VERIFIER_RE.fullmatch(exchange.code_verifier) or not hmac.compare_digest(
        s256(exchange.code_verifier), record.code_challenge
    ):
        return OAuthError("invalid_grant", "The code_verifier doesn't match (PKCE).")
    if exchange.resource and not same_resource(exchange.resource, record.resource):
        return OAuthError(
            "invalid_target",
            "resource must be the one sent in the authorization request.",
        )
    if not record.user.is_active:
        return OAuthError("invalid_grant", "The account is no longer active.")
    grant, pair = issue_mcp_grant(record.user, record.client)
    record.grant = grant
    record.save(update_fields=["grant"])
    return pair
