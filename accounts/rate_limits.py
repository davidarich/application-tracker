"""Rate limits for the public OAuth endpoints: the token endpoint and client
registration (api/routers/oauth.py), which anyone can call without logging
in.

Each limit allows a number of requests per fixed window (e.g. 30 a minute),
counted per client IP address, or in total across everyone (registration
has both, so many addresses can't fill the database with clients). Every
request counts, valid or not. The counts are kept in the database
(RateLimitBucket), so all processes and containers share them.

Limits are set in settings.OAUTH_RATE_LIMITS. Behind a reverse proxy, every
request seems to come from the proxy: set settings.TRUSTED_PROXY_COUNT to
the number of proxies in front of the app, so the client's address is read
from X-Forwarded-For instead.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from django.conf import settings
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone

from .models import RateLimitBucket

# Buckets untouched for this long are deleted (longer than any window).
STALE_AFTER = timedelta(days=1)

type LimitSettings = dict[str, dict[str, tuple[int, int]]]


@dataclass(frozen=True)
class Rule:
    requests: int
    window: timedelta


def client_ip(request: HttpRequest) -> str:
    """The client's IP address: REMOTE_ADDR, or, behind TRUSTED_PROXY_COUNT
    proxies, the address the outermost of them saw (in X-Forwarded-For,
    where each proxy appends the address it got the request from; the
    entries before that are up to the client, so they aren't trusted)."""
    remote = str(cast(object, request.META.get("REMOTE_ADDR", "")))
    proxies = cast(int, settings.TRUSTED_PROXY_COUNT)
    if proxies <= 0:
        return remote
    forwarded = [
        address.strip()
        for address in str(
            cast(object, request.META.get("HTTP_X_FORWARDED_FOR", ""))
        ).split(",")
        if address.strip()
    ]
    if len(forwarded) < proxies:
        return remote
    return forwarded[-proxies]


def rules(scope: str) -> dict[str, Rule]:
    """The limits for `scope` ("token" or "register"), by kind: "per_client"
    and/or "total"."""
    limits = cast(LimitSettings, settings.OAUTH_RATE_LIMITS).get(scope, {})
    return {
        kind: Rule(requests=requests, window=timedelta(seconds=seconds))
        for kind, (requests, seconds) in limits.items()
    }


def take(key: str, rule: Rule, now: datetime) -> int | None:
    """Count a request against the bucket `key`. Returns None if it's
    allowed, else the seconds until the bucket's window ends.

    The updates are conditional (on the window and the count as read), so
    requests at the same moment can't both take the last place."""
    bucket, created = RateLimitBucket.objects.get_or_create(
        key=key, defaults={"window_start": now, "count": 1}
    )
    if created:
        # Tidy up now and then: when a new client turns up.
        _ = RateLimitBucket.objects.filter(window_start__lt=now - STALE_AFTER).delete()
        return None
    buckets = RateLimitBucket.objects.filter(key=key)
    if now - bucket.window_start >= rule.window:
        if buckets.filter(window_start=bucket.window_start).update(
            window_start=now, count=1
        ):
            return None
        bucket.refresh_from_db()  # another request started the new window
    if buckets.filter(window_start=bucket.window_start, count__lt=rule.requests).update(
        count=F("count") + 1
    ):
        return None
    bucket.refresh_from_db()
    remaining = rule.window - (now - bucket.window_start)
    return max(1, math.ceil(remaining.total_seconds()))


def check_rate_limit(request: HttpRequest, scope: str) -> int | None:
    """Count `request` against `scope`'s limits. Returns None if it's
    allowed, else the seconds to wait before trying again (for a
    Retry-After header). A request refused by the per-client limit isn't
    counted against the total."""
    now = timezone.now()
    limits = rules(scope)
    buckets = {"per_client": f"{scope}:{client_ip(request)}", "total": f"{scope}:*"}
    for kind, key in buckets.items():  # per client first
        rule = limits.get(kind)
        if rule is not None and (wait := take(key, rule, now)):
            return wait
    return None
