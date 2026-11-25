"""The OAuth 2.0 token endpoint: the refresh token grant, with rotation."""

from datetime import timedelta
from typing import ClassVar, cast, override
from urllib.parse import urlencode

from django.http import HttpResponse
from django.test import Client, TestCase
from django.utils import timezone

from accounts.api_tokens import issue_grant, revoke_grant
from accounts.models import ApiGrant, ApiToken, User

from .helpers import Json

TOKEN_URL = "/api/v1/oauth/token"


def post_form(client: Client, data: dict[str, str]) -> HttpResponse:
    """POST `data` form-encoded, as OAuth asks (the test client defaults to multipart)."""
    return client.post(
        TOKEN_URL, urlencode(data), content_type="application/x-www-form-urlencoded"
    )


class TokenEndpointTests(TestCase):
    user: ClassVar[User]
    grant: ClassVar[ApiGrant]
    refresh_token: ClassVar[str]  # usable again in each test (the database is reset)

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("owner@example.com", "x")
        cls.grant, cls.refresh_token = issue_grant(cls.user, "Script")

    def exchange(self, refresh_token: str | None = None) -> HttpResponse:
        return post_form(
            self.client,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token or self.refresh_token,
            },
        )

    def refused(self, response: HttpResponse, error: str) -> str:
        """The error_description of an OAuth error response."""
        self.assertEqual(response.status_code, 400, response.content.decode())
        self.assertEqual(response["Cache-Control"], "no-store")
        body = cast(Json, response.json())
        self.assertEqual(body["error"], error)
        return cast(str, body["error_description"])

    def api_status(self, access_token: str) -> int:
        return self.client.get(
            "/api/v1/companies", headers={"Authorization": f"Bearer {access_token}"}
        ).status_code

    def test_a_refresh_token_is_exchanged_for_an_access_token_and_a_new_refresh_token(
        self,
    ):
        response = self.exchange()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (response["Cache-Control"], response["Pragma"]), ("no-store", "no-cache")
        )
        body = cast(Json, response.json())
        self.assertEqual(
            sorted(body), ["access_token", "expires_in", "refresh_token", "token_type"]
        )
        self.assertEqual((body["token_type"], body["expires_in"]), ("Bearer", 900))
        access_token, refresh_token = (
            cast(str, body["access_token"]),
            cast(str, body["refresh_token"]),
        )
        self.assertTrue(access_token.startswith("at_"))
        self.assertTrue(refresh_token.startswith("rt_"))
        self.assertNotEqual(refresh_token, self.refresh_token)
        self.assertEqual(self.api_status(access_token), 200)
        # The new refresh token works in turn.
        self.assertEqual(self.exchange(refresh_token).status_code, 200)

    def test_each_refresh_token_works_once_and_reuse_revokes_the_grant(self):
        first = cast(Json, self.exchange().json())
        description = self.refused(self.exchange(), "invalid_grant")
        self.assertIn("already used", description)
        grant = ApiGrant.objects.get(id=self.grant.id)
        self.assertIsNotNone(grant.revoked_at)
        # Everything the grant issued stops working, including the newest tokens.
        self.assertEqual(self.api_status(cast(str, first["access_token"])), 401)
        _ = self.refused(
            self.exchange(cast(str, first["refresh_token"])), "invalid_grant"
        )

    def test_expired_and_revoked_refresh_tokens_are_refused(self):
        _ = ApiToken.objects.filter(grant=self.grant).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIn("expired", self.refused(self.exchange(), "invalid_grant"))
        grant, refresh_token = issue_grant(self.user, "Other")
        _ = revoke_grant(self.user, grant.id)
        _ = self.refused(self.exchange(refresh_token), "invalid_grant")
        other_grant, other_token = issue_grant(self.user, "Third")
        _ = User.objects.filter(id=self.user.id).update(is_active=False)
        self.assertIn(
            "revoked", self.refused(self.exchange(other_token), "invalid_grant")
        )
        self.assertIsNone(ApiGrant.objects.get(id=other_grant.id).revoked_at)

    def test_unknown_tokens_and_access_tokens_are_refused(self):
        self.assertEqual(
            self.refused(self.exchange("rt_nope"), "invalid_grant"),
            "The refresh token isn't valid.",
        )
        access_token = cast(str, cast(Json, self.exchange().json())["access_token"])
        _ = self.refused(self.exchange(access_token), "invalid_grant")

    def test_bad_requests(self):
        self.assertEqual(
            self.refused(
                post_form(self.client, {"refresh_token": self.refresh_token}),
                "invalid_request",
            ),
            "grant_type is required.",
        )
        _ = self.refused(
            post_form(
                self.client,
                {"grant_type": "password", "username": "a", "password": "b"},
            ),
            "unsupported_grant_type",
        )
        self.assertEqual(
            self.refused(
                post_form(self.client, {"grant_type": "refresh_token"}),
                "invalid_request",
            ),
            "refresh_token is required.",
        )
        json_body = self.client.post(
            TOKEN_URL,
            {"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            content_type="application/json",
        )
        self.assertIn("form-encoded", self.refused(json_body, "invalid_request"))
        # None of those used up the refresh token.
        self.assertEqual(self.exchange().status_code, 200)

    def test_refreshing_tidies_up_expired_tokens(self):
        body = cast(Json, self.exchange().json())
        _ = ApiToken.objects.filter(grant=self.grant).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        _ = ApiToken.objects.filter(
            prefix=cast(str, body["refresh_token"])[:12]
        ).update(expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(
            self.exchange(cast(str, body["refresh_token"])).status_code, 200
        )
        kinds = sorted(
            ApiToken.objects.filter(grant=self.grant).values_list("kind", flat=True)
        )
        # The new access and refresh tokens, plus the used refresh token (kept
        # until it expires, to catch reuse).
        self.assertEqual(kinds, ["access", "refresh", "refresh"])

    def test_no_access_token_or_csrf_token_is_needed(self):
        client = Client(enforce_csrf_checks=True)
        response = post_form(
            client, {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        )
        self.assertEqual(response.status_code, 200)

    def test_the_grant_records_when_it_was_last_used(self):
        self.assertIsNone(self.grant.last_used_at)
        _ = self.exchange()
        self.assertIsNotNone(ApiGrant.objects.get(id=self.grant.id).last_used_at)

    def test_a_charset_on_the_form_content_type_is_fine(self):
        response = self.client.post(
            TOKEN_URL,
            urlencode(
                {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
            ),
            content_type="application/x-www-form-urlencoded; charset=utf-8",
        )
        self.assertEqual(response.status_code, 200)

    def test_tokens_are_never_read_from_the_url(self):
        query = urlencode(
            {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        )
        self.assertEqual(self.client.get(f"{TOKEN_URL}?{query}").status_code, 405)
        access_token = cast(str, cast(Json, self.exchange().json())["access_token"])
        response = self.client.get(f"/api/v1/companies?access_token={access_token}")
        self.assertEqual(response.status_code, 401)
