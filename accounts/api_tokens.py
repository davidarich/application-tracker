"""API grants and their OAuth 2.0 tokens (the refresh token grant, RFC 6749).

The API tokens page creates an ApiGrant and gives the program its first refresh
token. The program swaps a refresh token at the token endpoint
(api/routers/oauth.py) for:

- an access token, sent as `Authorization: Bearer at_...` with every API
  request, which expires after ACCESS_TOKEN_LIFETIME, and
- a new refresh token. Each refresh token works once (rotation); one sent a
  second time may have been copied, so the grant is revoked; there's no grace
  period, so two exchanges of one refresh token at the same moment count too.
  A refresh token not exchanged within REFRESH_TOKEN_LIFETIME expires.

Tokens are opaque: "at_" or "rt_" followed by 43 random URL-safe characters.
The first PREFIX_LENGTH characters find the row; the whole token is stored
only as a SHA-256 hash (a fast hash is enough for a random 256-bit secret,
unlike a password) and compared in constant time.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import final

from django.db import transaction
from django.utils import timezone

from .models import ApiGrant, ApiToken, User

Kind = ApiToken.Kind

ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
REFRESH_TOKEN_LIFETIME = timedelta(days=90)
TOKEN_STARTS = {Kind.ACCESS: "at_", Kind.REFRESH: "rt_"}
PREFIX_LENGTH = 12
# last_used_at is updated at most this often, so busy clients don't write on
# every request.
LAST_USED_PRECISION = timedelta(minutes=1)


@dataclass(frozen=True)
class TokenPair:
    """A token endpoint answer (RFC 6749 section 5.1)."""

    # Left out of repr(), so the tokens can't end up in logs or error reports.
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int  # seconds the access token lasts


@final
class RefreshError(Exception):
    """Why a refresh token was refused (an OAuth "invalid_grant" error)."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(grant: ApiGrant, kind: str) -> str:
    """Create a token of `kind` for `grant` and return it (only its hash is kept)."""
    lifetime = ACCESS_TOKEN_LIFETIME if kind == Kind.ACCESS else REFRESH_TOKEN_LIFETIME
    while True:
        token = TOKEN_STARTS[Kind(kind)] + secrets.token_urlsafe(32)
        prefix = token[:PREFIX_LENGTH]
        if not ApiToken.objects.filter(prefix=prefix).exists():
            break
    _ = ApiToken.objects.create(
        grant=grant,
        kind=kind,
        prefix=prefix,
        key_hash=hash_token(token),
        expires_at=timezone.now() + lifetime,
    )
    return token


def issue_grant(user: User, name: str) -> tuple[ApiGrant, str]:
    """Create a grant for `user`; return it with its first refresh token."""
    grant = ApiGrant.objects.create(user=user, name=name)
    return grant, new_token(grant, Kind.REFRESH)


def find_token(token: str, kind: str) -> ApiToken | None:
    """The stored token of `kind` matching `token`, if any (expired or not)."""
    start = TOKEN_STARTS[Kind(kind)]
    if not token.startswith(start) or len(token) <= PREFIX_LENGTH:
        return None
    record = (
        ApiToken.objects.filter(prefix=token[:PREFIX_LENGTH], kind=kind)
        .select_related("grant__user")
        .first()
    )
    if record is None or not hmac.compare_digest(record.key_hash, hash_token(token)):
        return None
    return record


def grant_is_live(grant: ApiGrant) -> bool:
    return grant.revoked_at is None and grant.user.is_active


def touch(grant: ApiGrant) -> None:
    now = timezone.now()
    if grant.last_used_at is None or now - grant.last_used_at >= LAST_USED_PRECISION:
        _ = ApiGrant.objects.filter(id=grant.id).update(last_used_at=now)


def user_for_access_token(token: str) -> User | None:
    """The active user of a live, unexpired access token, else None."""
    record = find_token(token, Kind.ACCESS)
    if record is None or record.expires_at <= timezone.now():
        return None
    if not grant_is_live(record.grant):
        return None
    touch(record.grant)
    return record.grant.user


def refresh_tokens(refresh_token: str) -> TokenPair:
    """Swap a refresh token for a new access token and refresh token.

    Raises RefreshError if the refresh token is unknown, expired, revoked or
    already used (which also revokes its grant).
    """
    now = timezone.now()
    with transaction.atomic():
        outcome = _rotate(refresh_token, now)
    if isinstance(outcome, str):
        raise RefreshError(outcome)
    return outcome


def _rotate(refresh_token: str, now: datetime) -> TokenPair | str:
    """refresh_tokens()'s work, in its transaction; returns the refusal reason
    instead of raising, so revoking a reused token's grant is kept."""
    record = find_token(refresh_token, Kind.REFRESH)
    if record is None:
        return "The refresh token isn't valid."
    grant = record.grant
    if not grant_is_live(grant):
        return "The refresh token has been revoked."
    if record.expires_at <= now:
        return (
            "The refresh token has expired. Create a new one on your API tokens page."
        )
    # Claim the token; only one request can (a used one has used_at set).
    claimed = ApiToken.objects.filter(id=record.id, used_at__isnull=True).update(
        used_at=now
    )
    if not claimed:
        end_grant(grant)
        return (
            "The refresh token was already used, so it may have been copied. "
            + "Its access has been revoked: create a new token on your API tokens page."
        )
    # Tidy up: expired tokens are no use (used refresh tokens are kept until
    # they expire, to catch reuse).
    _ = ApiToken.objects.filter(grant=grant, expires_at__lte=now).delete()
    touch(grant)
    return TokenPair(
        access_token=new_token(grant, Kind.ACCESS),
        refresh_token=new_token(grant, Kind.REFRESH),
        expires_in=int(ACCESS_TOKEN_LIFETIME.total_seconds()),
    )


def end_grant(grant: ApiGrant) -> None:
    """Revoke `grant`: its tokens stop working at once."""
    _ = ApiGrant.objects.filter(id=grant.id).update(revoked_at=timezone.now())
    _ = ApiToken.objects.filter(grant=grant).delete()


def active_grants_for(user: User) -> list[ApiGrant]:
    return list(ApiGrant.objects.filter(user=user, revoked_at__isnull=True))


def revoke_grant(user: User, grant_id: uuid.UUID) -> ApiGrant | None:
    """Revoke one of `user`'s grants; None if they have no such (live) grant."""
    grant = ApiGrant.objects.filter(
        user=user, id=grant_id, revoked_at__isnull=True
    ).first()
    if grant is not None:
        end_grant(grant)
    return grant
