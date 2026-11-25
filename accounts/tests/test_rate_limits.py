"""Rate limits on the public OAuth endpoints: the token endpoint and client
registration (accounts/rate_limits.py)."""

from datetime import timedelta
from typing import cast

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from ..models import RateLimitBucket
from ..rate_limits import client_ip

TOKEN = "/api/v1/oauth/token"
REGISTER = "/api/v1/oauth/register"
FORM = "application/x-www-form-urlencoded"
LIMITS = {
    "token": {"per_client": (3, 60)},
    "register": {"per_client": (2, 3600), "total": (3, 3600)},
}

type Json = dict[str, object]


@override_settings(OAUTH_RATE_LIMITS=LIMITS)
class RateLimitTests(TestCase):
    def token(self, address: str = "203.0.113.1", **headers: str) -> HttpResponse:
        # A refresh token that doesn't exist: refused, but still counted.
        return self.client.post(
            TOKEN,
            "grant_type=refresh_token&refresh_token=rt_nope",
            content_type=FORM,
            REMOTE_ADDR=address,
            headers=headers,
        )

    def register(self, address: str = "203.0.113.1") -> HttpResponse:
        return self.client.post(
            REGISTER,
            {"redirect_uris": ["http://localhost/cb"]},
            content_type="application/json",
            REMOTE_ADDR=address,
        )

    def assert_limited(self, response: HttpResponse, wait: int) -> None:
        self.assertEqual(response.status_code, 429, response.content.decode())
        payload = cast(Json, response.json())
        self.assertEqual(payload["error"], "too_many_requests")
        self.assertIn("Try again in", cast(str, payload["error_description"]))
        retry_after = int(response["Retry-After"])
        self.assertTrue(0 < retry_after <= wait, retry_after)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_the_token_endpoint_is_limited_per_address(self):
        for _ in range(3):
            self.assertEqual(self.token().status_code, 400)  # counted, though refused
        self.assert_limited(self.token(), 60)
        # Another address has its own limit.
        self.assertEqual(self.token("203.0.113.2").status_code, 400)

    def test_the_limit_resets_when_its_window_ends(self):
        for _ in range(3):
            _ = self.token()
        self.assert_limited(self.token(), 60)
        _ = RateLimitBucket.objects.update(
            window_start=timezone.now() - timedelta(seconds=61)
        )
        self.assertEqual(self.token().status_code, 400)
        self.assertEqual(RateLimitBucket.objects.get().count, 1)

    def test_registration_is_limited_per_address_and_in_total(self):
        self.assertEqual(self.register("198.51.100.1").status_code, 201)
        self.assertEqual(self.register("198.51.100.1").status_code, 201)
        self.assert_limited(self.register("198.51.100.1"), 3600)
        # Refused by its address's limit, so not counted in the total.
        self.assertEqual(self.register("198.51.100.2").status_code, 201)
        # The total (3) is reached, whatever the address.
        self.assert_limited(self.register("198.51.100.3"), 3600)

    def test_a_429_can_be_read_by_browser_clients(self):
        for _ in range(3):
            _ = self.token()
        response = self.token(Origin="https://app.example")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("Retry-After", response["Access-Control-Expose-Headers"])

    def test_other_endpoints_are_not_limited(self):
        for _ in range(5):
            self.assertEqual(self.client.get("/api/v1/jobs").status_code, 401)
        self.assertFalse(RateLimitBucket.objects.exists())

    def test_stale_buckets_are_tidied_up(self):
        _ = RateLimitBucket.objects.create(
            key="token:192.0.2.9", window_start=timezone.now() - timedelta(days=2)
        )
        _ = self.token()
        self.assertEqual(
            list(RateLimitBucket.objects.values_list("key", flat=True)),
            ["token:203.0.113.1"],
        )

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_behind_a_proxy_each_client_has_its_own_limit(self):
        proxy = "10.0.0.5"
        for _ in range(3):
            _ = self.token(proxy, **{"X-Forwarded-For": "203.0.113.7"})
        self.assert_limited(self.token(proxy, **{"X-Forwarded-For": "203.0.113.7"}), 60)
        # Another client behind the same proxy isn't limited...
        self.assertEqual(
            self.token(proxy, **{"X-Forwarded-For": "203.0.113.8"}).status_code, 400
        )
        # ...and a client can't dodge its limit by adding addresses itself.
        spoofed = self.token(proxy, **{"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
        self.assert_limited(spoofed, 60)


class ClientIpTests(TestCase):
    def ip(self, forwarded: str | None = None) -> str:
        request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.5")
        if forwarded is not None:
            request.META["HTTP_X_FORWARDED_FOR"] = forwarded
        return client_ip(request)

    def test_without_proxies_x_forwarded_for_is_ignored(self):
        self.assertEqual(self.ip("203.0.113.7"), "10.0.0.5")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_with_proxies_the_outermost_proxys_view_is_used(self):
        self.assertEqual(self.ip("1.1.1.1, 203.0.113.7, 10.0.0.1"), "203.0.113.7")
        self.assertEqual(self.ip("203.0.113.7, 10.0.0.1"), "203.0.113.7")
        # Fewer entries than proxies: not set up as expected, so not trusted.
        self.assertEqual(self.ip("203.0.113.7"), "10.0.0.5")
        self.assertEqual(self.ip(), "10.0.0.5")


class DefaultLimitTests(TestCase):
    def test_the_defaults_allow_normal_use(self):
        # A client refreshes about every 15 minutes: a few retries a minute
        # are well within the limit.
        for _ in range(10):
            response = self.client.post(
                TOKEN, "grant_type=refresh_token&refresh_token=rt_x", content_type=FORM
            )
            self.assertEqual(response.status_code, 400)
