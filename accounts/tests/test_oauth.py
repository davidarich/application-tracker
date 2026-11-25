"""OAuth 2.0 for MCP clients (accounts/oauth.py): registering a client, the
consent page, swapping the code (with PKCE) for tokens, refreshing them, and
seeing and disconnecting connected apps on the API tokens page."""

import secrets
from datetime import timedelta
from typing import ClassVar, cast, override
from urllib.parse import parse_qs, urlencode, urlsplit

from django.http import HttpResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ..api_tokens import Audience, user_for_access_token
from ..models import ApiGrant, ApiToken, AuthorizationCode, OAuthClient, User
from ..oauth import s256

type Json = dict[str, object]

REGISTER = "/api/v1/oauth/register"
TOKEN = "/api/v1/oauth/token"
AUTHORIZE = reverse("accounts:oauth_authorize")
METADATA = "/.well-known/oauth-authorization-server"
TOKENS_PAGE = reverse("accounts:api_tokens")
REDIRECT = "http://localhost:33418/callback"
RESOURCE = "http://localhost:8002/mcp"
FORM = "application/x-www-form-urlencoded"
# The PKCE code verifier the tests' client uses.
VERIFIER = secrets.token_urlsafe(48)


def query_of(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


class OAuthTestCase(TestCase):
    user: ClassVar[User]
    oauth_client: ClassVar[OAuthClient]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")
        cls.oauth_client = OAuthClient.objects.create(
            client_id="agent-app", name="Agent App", redirect_uris=[REDIRECT]
        )

    def register(self, metadata: object) -> HttpResponse:
        return self.client.post(REGISTER, metadata, content_type="application/json")

    def authorize_params(self, **changes: str) -> dict[str, str]:
        params = {
            "response_type": "code",
            "client_id": self.oauth_client.client_id,
            "redirect_uri": REDIRECT,
            "state": "xyz",
            "code_challenge": s256(VERIFIER),
            "code_challenge_method": "S256",
            "resource": RESOURCE,
            **changes,
        }
        return {key: value for key, value in params.items() if value != "-"}

    def authorize_get(self, **changes: str) -> HttpResponse:
        query = urlencode(self.authorize_params(**changes))
        return self.client.get(AUTHORIZE + "?" + query)

    def allow(self, **changes: str) -> dict[str, str]:
        """Allow on the consent page; the query the client is sent back with."""
        self.client.force_login(self.user)
        response = self.client.post(
            AUTHORIZE, {**self.authorize_params(**changes), "decision": "allow"}
        )
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertTrue(location.startswith(REDIRECT + "?"), location)
        return query_of(location)

    def exchange(self, code: str, **changes: str) -> HttpResponse:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": self.oauth_client.client_id,
            "code_verifier": VERIFIER,
            **changes,
        }
        data = {key: value for key, value in data.items() if value != "-"}
        return self.token_request(data)

    def token_request(self, data: dict[str, str]) -> HttpResponse:
        return self.client.post(TOKEN, urlencode(data), content_type=FORM)

    def oauth_error(self, response: HttpResponse, error: str) -> str:
        self.assertEqual(response.status_code, 400, response.content.decode())
        payload = cast(Json, response.json())
        self.assertEqual(payload["error"], error, payload)
        return cast(str, payload["error_description"])


class RegistrationTests(OAuthTestCase):
    def test_a_client_registers_and_gets_a_client_id(self):
        response = self.register(
            {
                "client_name": "  Claude   Code ",
                "redirect_uris": [REDIRECT, "https://app.example/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
            }
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        info = cast(Json, response.json())
        client = OAuthClient.objects.get(client_id=cast(str, info["client_id"]))
        self.assertEqual(client.name, "Claude Code")
        self.assertEqual(info["client_name"], "Claude Code")
        self.assertEqual(
            info["redirect_uris"], [REDIRECT, "https://app.example/callback"]
        )
        # Public clients only: a secret method asked for is replaced.
        self.assertEqual(info["token_endpoint_auth_method"], "none")
        self.assertNotIn("client_secret", info)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_a_name_is_optional(self):
        info = cast(Json, self.register({"redirect_uris": [REDIRECT]}).json())
        self.assertEqual(info["client_name"], "Unnamed app")

    def test_redirect_uris_must_be_https_or_loopback(self):
        for uri in (
            "http://app.example/callback",
            "https://app.example/callback#frag",
            "ftp://app.example/",
            "cursor://callback",
            "https:///nohost",
            "not a url",
        ):
            with self.subTest(uri=uri):
                response = self.register({"redirect_uris": [uri]})
                _ = self.oauth_error(response, "invalid_redirect_uri")
        for uri in (
            "http://127.0.0.1:5000/cb",
            "http://[::1]/cb",
            "http://localhost/cb",
            "https://app.example/cb?x=1",
        ):
            with self.subTest(uri=uri):
                self.assertEqual(
                    self.register({"redirect_uris": [uri]}).status_code, 201
                )

    def test_bad_metadata_is_refused(self):
        cases: list[tuple[object, str]] = [
            ({}, "invalid_redirect_uri"),
            ({"redirect_uris": REDIRECT}, "invalid_redirect_uri"),
            ({"redirect_uris": [REDIRECT] * 11}, "invalid_redirect_uri"),
            (
                {"redirect_uris": [REDIRECT], "grant_types": ["client_credentials"]},
                "invalid_client_metadata",
            ),
            (
                {"redirect_uris": [REDIRECT], "response_types": ["token"]},
                "invalid_client_metadata",
            ),
            (
                {"redirect_uris": [REDIRECT], "client_name": 5},
                "invalid_client_metadata",
            ),
            ([REDIRECT], "invalid_client_metadata"),
        ]
        for metadata, error in cases:
            with self.subTest(metadata=metadata):
                _ = self.oauth_error(self.register(metadata), error)
        response = self.client.post(
            REGISTER, "{not json", content_type="application/json"
        )
        _ = self.oauth_error(response, "invalid_client_metadata")

    def test_registering_tidies_up_old_clients_that_were_never_allowed(self):
        old = timezone.now() - timedelta(days=2)
        unused = OAuthClient.objects.create(
            client_id="old", name="Old", redirect_uris=[REDIRECT]
        )
        used = OAuthClient.objects.create(
            client_id="used", name="Used", redirect_uris=[REDIRECT]
        )
        _ = ApiGrant.objects.create(
            user=self.user, name="Used", audience=Audience.MCP, client=used
        )
        _ = OAuthClient.objects.filter(id__in=[unused.id, used.id]).update(
            created_at=old
        )
        _ = self.register({"redirect_uris": [REDIRECT]})
        self.assertFalse(OAuthClient.objects.filter(id=unused.id).exists())
        self.assertTrue(OAuthClient.objects.filter(id=used.id).exists())
        self.assertTrue(OAuthClient.objects.filter(id=self.oauth_client.id).exists())

    def test_browser_clients_can_register_and_use_the_token_endpoint(self):
        for path in (REGISTER, TOKEN, METADATA):
            with self.subTest(path=path):
                preflight = self.client.options(
                    path, headers={"Origin": "https://app.example"}
                )
                self.assertEqual(preflight.status_code, 204)
                self.assertEqual(preflight["Access-Control-Allow-Origin"], "*")
                self.assertIn("POST", preflight["Access-Control-Allow-Methods"])
        response = self.register({"redirect_uris": [REDIRECT]})
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        # Not other API endpoints.
        response = self.client.get("/api/v1/jobs")
        self.assertFalse(response.has_header("Access-Control-Allow-Origin"))


class MetadataTests(OAuthTestCase):
    def test_the_authorization_server_metadata(self):
        response = self.client.get(METADATA)
        self.assertEqual(response.status_code, 200)
        metadata = cast(Json, response.json())
        self.assertEqual(
            metadata,
            {
                "issuer": "http://localhost:8000",
                "authorization_endpoint": "http://localhost:8000/oauth/authorize/",
                "token_endpoint": "http://localhost:8000/api/v1/oauth/token",
                "registration_endpoint": "http://localhost:8000/api/v1/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "authorization_response_iss_parameter_supported": True,
            },
        )
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    @override_settings(OAUTH_ISSUER="https://tracker.example")
    def test_the_issuer_comes_from_the_settings(self):
        metadata = cast(Json, self.client.get(METADATA).json())
        self.assertEqual(metadata["issuer"], "https://tracker.example")
        self.assertEqual(
            metadata["authorization_endpoint"],
            "https://tracker.example/oauth/authorize/",
        )


class AuthorizeTests(OAuthTestCase):
    def test_logging_in_comes_first(self):
        response = self.authorize_get()
        self.assertEqual(response.status_code, 302)
        login = urlsplit(response["Location"])
        self.assertEqual(login.path, reverse("tracker:login"))
        self.assertTrue(
            query_of(response["Location"])["next"].startswith(AUTHORIZE + "?")
        )

    def test_the_consent_page(self):
        self.client.force_login(self.user)
        response = self.authorize_get()
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn("Connect Agent App?", page)
        self.assertIn("the name the app gave itself", page)
        self.assertIn("localhost:33418", page)
        self.assertIn('value="allow"', page)
        self.assertIn('value="deny"', page)
        self.assertIn(f'name="code_challenge" value="{s256(VERIFIER)}"', page)
        self.assertNotIn("add and change skills", page)
        # Not framed by other sites, nor cached.
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertFalse(AuthorizationCode.objects.exists())

    def test_staff_are_told_the_app_can_change_skills(self):
        _ = User.objects.filter(id=self.user.id).update(is_staff=True)
        self.client.force_login(self.user)
        self.assertContains(self.authorize_get(), "add and change skills")

    def test_a_wrong_client_or_redirect_uri_is_shown_never_redirected(self):
        self.client.force_login(self.user)
        for changes in (
            {"client_id": "nope"},
            {"client_id": "-"},
            {"redirect_uri": "https://evil.example/callback"},
            {"redirect_uri": "-"},
            {"redirect_uri": "http://localhost:33418/other"},
        ):
            with self.subTest(changes=changes):
                response = self.authorize_get(**changes)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "Can't connect the app", status_code=400)

    def test_a_loopback_redirect_uri_may_use_another_port(self):
        self.client.force_login(self.user)
        response = self.authorize_get(redirect_uri="http://localhost:51234/callback")
        self.assertEqual(response.status_code, 200)

    def test_other_mistakes_are_sent_back_to_the_client(self):
        self.client.force_login(self.user)
        cases = [
            ({"response_type": "token"}, "unsupported_response_type"),
            ({"code_challenge": "-"}, "invalid_request"),
            ({"code_challenge_method": "plain"}, "invalid_request"),
            ({"code_challenge_method": "-"}, "invalid_request"),
            ({"code_challenge": "too-short"}, "invalid_request"),
            ({"resource": "https://other.example/mcp"}, "invalid_target"),
        ]
        for changes, error in cases:
            with self.subTest(changes=changes):
                response = self.authorize_get(**changes)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(REDIRECT + "?"))
                query = query_of(response["Location"])
                self.assertEqual(query["error"], error)
                self.assertEqual(query["state"], "xyz")
                self.assertEqual(query["iss"], "http://localhost:8000")

    def test_a_missing_resource_means_the_mcp_server(self):
        query = self.allow(resource="-")
        self.assertEqual(AuthorizationCode.objects.get().resource, RESOURCE)
        self.assertIn("code", query)

    def test_denying_sends_the_client_back_with_an_error(self):
        self.client.force_login(self.user)
        response = self.client.post(
            AUTHORIZE, {**self.authorize_params(), "decision": "deny"}
        )
        query = query_of(response["Location"])
        self.assertEqual(query["error"], "access_denied")
        self.assertEqual(query["state"], "xyz")
        self.assertFalse(AuthorizationCode.objects.exists())

    def test_allowing_sends_the_client_back_with_a_code(self):
        query = self.allow()
        self.assertEqual(query["state"], "xyz")
        self.assertEqual(query["iss"], "http://localhost:8000")
        code = query["code"]
        self.assertTrue(code.startswith("ac_"))
        record = AuthorizationCode.objects.get()
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.client, self.oauth_client)
        self.assertNotIn(code, record.key_hash)  # only its hash is stored
        self.assertEqual(record.prefix, code[:12])
        self.assertFalse(ApiGrant.objects.exists())  # not until it's swapped

    def test_a_redirect_uri_with_a_query_keeps_it(self):
        self.oauth_client.redirect_uris = ["https://app.example/cb?tenant=1"]
        self.oauth_client.save()
        self.client.force_login(self.user)
        response = self.client.post(
            AUTHORIZE,
            {
                **self.authorize_params(redirect_uri="https://app.example/cb?tenant=1"),
                "decision": "allow",
            },
        )
        query = query_of(response["Location"])
        self.assertEqual(query["tenant"], "1")
        self.assertIn("code", query)

    def test_the_consent_post_is_checked_again(self):
        self.client.force_login(self.user)
        response = self.client.post(
            AUTHORIZE,
            {
                **self.authorize_params(redirect_uri="https://evil.example/cb"),
                "decision": "allow",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuthorizationCode.objects.exists())

    def test_the_consent_post_needs_the_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            AUTHORIZE, {**self.authorize_params(), "decision": "allow"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuthorizationCode.objects.exists())


class CodeExchangeTests(OAuthTestCase):
    def test_a_code_is_swapped_for_an_mcp_grants_tokens(self):
        code = self.allow()["code"]
        response = self.exchange(code, resource=RESOURCE)
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response["Cache-Control"], "no-store")
        tokens = cast(Json, response.json())
        self.assertEqual(tokens["token_type"], "Bearer")
        self.assertEqual(tokens["expires_in"], 900)
        grant = ApiGrant.objects.get()
        self.assertEqual(grant.user, self.user)
        self.assertEqual(grant.audience, Audience.MCP)
        self.assertEqual(grant.client, self.oauth_client)
        self.assertEqual(grant.name, "Agent App")
        access_token = cast(str, tokens["access_token"])
        # The tokens work with the MCP server, not the JSON API.
        self.assertEqual(user_for_access_token(access_token, Audience.MCP), self.user)
        self.assertIsNone(user_for_access_token(access_token))
        api = self.client.get(
            "/api/v1/jobs", headers={"Authorization": f"Bearer {access_token}"}
        )
        self.assertEqual(api.status_code, 401)

    def test_a_code_works_once_and_reuse_revokes_its_grant(self):
        code = self.allow()["code"]
        self.assertEqual(self.exchange(code).status_code, 200)
        grant = ApiGrant.objects.get()
        description = self.oauth_error(self.exchange(code), "invalid_grant")
        self.assertIn("already used", description)
        grant.refresh_from_db()
        self.assertIsNotNone(grant.revoked_at)
        self.assertFalse(ApiToken.objects.filter(grant=grant).exists())

    def test_a_wrong_verifier_is_refused_and_spends_the_code(self):
        code = self.allow()["code"]
        description = self.oauth_error(
            self.exchange(code, code_verifier=secrets.token_urlsafe(48)),
            "invalid_grant",
        )
        self.assertIn("code_verifier", description)
        # Even the right verifier can't use it now.
        _ = self.oauth_error(self.exchange(code), "invalid_grant")
        self.assertFalse(ApiGrant.objects.exists())

    def test_mismatches_are_refused(self):
        other = OAuthClient.objects.create(
            client_id="other", name="Other", redirect_uris=[REDIRECT]
        )
        cases = [
            ({"client_id": other.client_id}, "invalid_grant"),
            ({"redirect_uri": "http://localhost:9999/callback"}, "invalid_grant"),
            ({"code_verifier": "short"}, "invalid_grant"),
            ({"resource": "https://other.example/mcp"}, "invalid_target"),
        ]
        for changes, error in cases:
            with self.subTest(changes=changes):
                code = self.allow()["code"]
                _ = self.oauth_error(self.exchange(code, **changes), error)
        self.assertFalse(ApiGrant.objects.exists())

    def test_expired_and_unknown_codes_are_refused(self):
        code = self.allow()["code"]
        _ = AuthorizationCode.objects.update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIn("expired", self.oauth_error(self.exchange(code), "invalid_grant"))
        _ = self.oauth_error(self.exchange("ac_" + "x" * 43), "invalid_grant")
        _ = self.oauth_error(self.exchange("nonsense"), "invalid_grant")

    def test_an_inactive_user_gets_no_tokens(self):
        code = self.allow()["code"]
        _ = User.objects.filter(id=self.user.id).update(is_active=False)
        _ = self.oauth_error(self.exchange(code), "invalid_grant")

    def test_parameters_are_required(self):
        for name in ("code", "redirect_uri", "client_id", "code_verifier"):
            with self.subTest(name=name):
                changes = {name: "-"}
                if name != "code":
                    changes["code"] = "ac_whatever"
                response = self.exchange(changes.pop("code", "-"), **changes)
                self.assertIn(name, self.oauth_error(response, "invalid_request"))

    def test_issuing_a_code_tidies_up_expired_ones(self):
        _ = self.allow()
        _ = AuthorizationCode.objects.update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        _ = self.allow()
        self.assertEqual(AuthorizationCode.objects.count(), 1)


class RefreshTests(OAuthTestCase):
    def tokens(self) -> Json:
        code = self.allow()["code"]
        return cast(Json, self.exchange(code).json())

    def refresh(self, refresh_token: object, **extra: str) -> HttpResponse:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": cast(str, refresh_token),
            **extra,
        }
        return self.token_request(data)

    def test_an_mcp_grant_refreshes_with_its_client_id(self):
        tokens = self.tokens()
        response = self.refresh(tokens["refresh_token"], client_id="agent-app")
        self.assertEqual(response.status_code, 200, response.content.decode())
        new = cast(Json, response.json())
        self.assertEqual(
            user_for_access_token(cast(str, new["access_token"]), Audience.MCP),
            self.user,
        )

    def test_another_or_no_client_id_is_refused(self):
        tokens = self.tokens()
        for extra in ({}, {"client_id": "someone-else"}):
            with self.subTest(extra=extra):
                description = self.oauth_error(
                    self.refresh(tokens["refresh_token"], **extra), "invalid_grant"
                )
                self.assertIn("another client", description)
        # The refresh token wasn't used up by the refused requests.
        response = self.refresh(tokens["refresh_token"], client_id="agent-app")
        self.assertEqual(response.status_code, 200)


class ConnectedAppsPageTests(OAuthTestCase):
    def connect(self, user: User | None = None) -> ApiGrant:
        return ApiGrant.objects.create(
            user=user or self.user,
            name="Agent App",
            audience=Audience.MCP,
            client=self.oauth_client,
        )

    def test_connected_apps_are_listed_apart_from_tokens(self):
        self.client.force_login(self.user)
        page = self.client.get(TOKENS_PAGE).content.decode()
        self.assertIn('id="connected-apps"', page)
        self.assertIn("No apps are connected.", page)
        grant = self.connect()
        page = self.client.get(TOKENS_PAGE).content.decode()
        apps = page[page.index('id="connected-apps"') :]
        tokens = page[page.index('id="api-tokens"') : page.index('id="connected-apps"')]
        self.assertIn("Agent App", apps)
        self.assertIn("localhost:33418", apps)
        self.assertIn("Never used", apps)
        self.assertIn(reverse("accounts:api_token_revoke", args=[grant.id]), apps)
        self.assertIn("Disconnect", apps)
        self.assertNotIn("Agent App", tokens)
        self.assertIn("You don't have any API tokens.", tokens)

    def test_disconnecting_an_app_ends_its_access(self):
        grant = self.connect()
        _ = ApiToken.objects.create(
            grant=grant,
            kind="access",
            prefix="at_abcdefghi",
            key_hash="x",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:api_token_revoke", args=[grant.id]), follow=True
        )
        self.assertContains(response, "Disconnected Agent App.")
        self.assertContains(response, "No apps are connected.")
        grant.refresh_from_db()
        self.assertIsNotNone(grant.revoked_at)
        self.assertFalse(ApiToken.objects.filter(grant=grant).exists())

    def test_other_users_apps_are_not_shown_or_revocable(self):
        other = User.objects.create_user("bob@example.com", "x")
        grant = self.connect(other)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(TOKENS_PAGE), "No apps are connected.")
        response = self.client.post(
            reverse("accounts:api_token_revoke", args=[grant.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_clients_and_grants_in_the_admin(self):
        admin = User.objects.create_superuser("admin@example.com", "x")
        grant = self.connect()
        self.client.force_login(admin)
        page = self.client.get(reverse("admin:accounts_oauthclient_changelist"))
        self.assertContains(page, "Agent App")
        self.assertContains(page, "agent-app")
        self.assertEqual(
            self.client.get(reverse("admin:accounts_oauthclient_add")).status_code, 403
        )
        page = self.client.get(
            reverse("admin:accounts_apigrant_change", args=[grant.id])
        )
        self.assertContains(page, "MCP server")
