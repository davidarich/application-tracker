"""API authentication: OAuth 2.0 access tokens (RFC 6750), never the site's
login session or a refresh token."""

from datetime import timedelta
from typing import cast

from django.http import HttpResponse
from django.test import Client
from django.utils import timezone

from accounts.api_tokens import issue_grant, refresh_tokens, revoke_grant
from accounts.models import ApiGrant, ApiToken, User

from .helpers import ApiTestCase, Json

MISSING = "An access token is required: send Authorization: Bearer <access token>."
INVALID = (
    "The access token isn't valid or has expired. "
    + "Get a new one at /api/v1/oauth/token with your refresh token."
)
INVALID_CHALLENGE = (
    'Bearer realm="api", error="invalid_token", error_description="' + INVALID + '"'
)


class AccessTokenTests(ApiTestCase):
    def assert_refused(
        self, response: HttpResponse, message: str, challenge: str
    ) -> None:
        self.assertEqual(response.status_code, 401)
        self.assertEqual(cast(Json, response.json()), {"detail": message})
        self.assertEqual(response["WWW-Authenticate"], challenge)

    def test_a_valid_access_token_is_accepted(self):
        self.assertEqual(self.call("GET", "companies").status_code, 200)

    def test_a_missing_token_asks_for_one(self):
        for header in ("", "Bearer", "Token " + self.token):
            response = self.client.get(
                "/api/v1/companies", headers={"Authorization": header} if header else {}
            )
            self.assert_refused(response, MISSING, 'Bearer realm="api"')

    def test_a_wrong_or_expired_access_token_is_invalid(self):
        wrong_secret = self.token[:-4] + "abcd"
        self.assert_refused(
            self.call("GET", "companies", token=wrong_secret),
            INVALID,
            INVALID_CHALLENGE,
        )
        _ = ApiToken.objects.filter(kind=ApiToken.Kind.ACCESS).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assert_refused(self.call("GET", "companies"), INVALID, INVALID_CHALLENGE)

    def test_a_refresh_token_is_not_an_access_token(self):
        _grant, refresh_token = issue_grant(self.user, "Script")
        response = self.call("GET", "companies", token=refresh_token)
        message = (
            "That's a refresh token. Exchange it at /api/v1/oauth/token for an "
            + "access token, and send that instead."
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(cast(Json, response.json()), {"detail": message})
        self.assertIn('error="invalid_token"', response["WWW-Authenticate"])

    def test_revoked_grants_and_inactive_users_are_refused(self):
        _ = revoke_grant(self.user, self.grant.id)
        self.assertEqual(self.call("GET", "companies").status_code, 401)
        _grant, refresh_token = issue_grant(self.user, "Another")
        token = refresh_tokens(refresh_token).access_token
        self.assertEqual(self.call("GET", "companies", token=token).status_code, 200)
        _ = User.objects.filter(id=self.user.id).update(is_active=False)
        self.assertEqual(self.call("GET", "companies", token=token).status_code, 401)

    def test_the_login_session_is_not_enough(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/v1/companies").status_code, 401)

    def test_no_csrf_token_is_needed(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            "/api/v1/companies",
            {"name": "Acme"},
            content_type="application/json",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 201)

    def test_only_hashes_of_tokens_are_stored(self):
        record = ApiToken.objects.get(prefix=self.token[:12])
        self.assertEqual(record.kind, ApiToken.Kind.ACCESS)
        self.assertTrue(self.token.startswith("at_"))
        self.assertEqual(len(record.key_hash), 64)
        self.assertNotIn(self.token[12:], record.key_hash)

    def test_access_tokens_last_15_minutes(self):
        record = ApiToken.objects.get(prefix=self.token[:12])
        lifetime = record.expires_at - record.created_at
        self.assertAlmostEqual(lifetime.total_seconds(), 15 * 60, delta=5)

    def test_last_used_is_recorded_at_most_once_a_minute(self):
        def last_used() -> object:
            return ApiGrant.objects.get(id=self.grant.id).last_used_at

        recent = timezone.now() - timedelta(seconds=30)
        _ = ApiGrant.objects.filter(id=self.grant.id).update(last_used_at=recent)
        _ = self.call("GET", "companies")
        self.assertEqual(last_used(), recent)
        stale = timezone.now() - timedelta(minutes=2)
        _ = ApiGrant.objects.filter(id=self.grant.id).update(last_used_at=stale)
        _ = self.call("GET", "companies")
        self.assertNotEqual(last_used(), stale)


class DocsTests(ApiTestCase):
    def test_the_docs_and_schema_need_no_token(self):
        docs = self.client.get("/api/v1/docs")
        self.assertEqual(docs.status_code, 200)
        self.assertContains(docs, "/static/ninja/swagger-ui-bundle.js")  # not a CDN
        schema = cast(Json, self.client.get("/api/v1/openapi.json").json())
        paths = cast(dict[str, dict[str, Json]], schema["paths"])
        self.assertEqual(cast(Json, schema["info"])["title"], "Job Tracker API")
        self.assertEqual(
            sorted(paths),
            [
                "/api/v1/companies",
                "/api/v1/companies/{company_id}",
                "/api/v1/jobs",
                "/api/v1/jobs/{job_id}",
                "/api/v1/oauth/register",
                "/api/v1/oauth/token",
                "/api/v1/skills",
                "/api/v1/skills/{skill_id}",
            ],
        )
        # Updating, but no deleting, yet.
        methods = {m for path in paths.values() for m in path}
        self.assertEqual(methods, {"get", "post", "patch"})
        body = cast(Json, paths["/api/v1/oauth/token"]["post"]["requestBody"])
        self.assertIn("application/x-www-form-urlencoded", cast(Json, body["content"]))
