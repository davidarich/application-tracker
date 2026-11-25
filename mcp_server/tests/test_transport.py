"""The MCP server over HTTP: who may call it (MCP access tokens only), the
OAuth metadata that tells clients where to log in, and the Host and Origin
checks."""

from datetime import timedelta
from typing import cast

from django.test import override_settings
from django.utils import timezone

from accounts.api_tokens import end_grant, issue_grant, refresh_tokens
from accounts.models import ApiToken, User

from .helpers import Json, McpTestCase

INITIALIZE: Json = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
METADATA_URL = "http://localhost:8002/.well-known/oauth-protected-resource/mcp"
SECURITY_LOGGER = "mcp.server.transport_security"


class AuthTests(McpTestCase):
    def initialize(
        self, token: str | None, headers: dict[str, str] | None = None
    ) -> int:
        """The status of an initialize request sent with `token`."""
        all_headers = {
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        if token is not None:
            all_headers["Authorization"] = f"Bearer {token}"
        return self.post("/mcp", INITIALIZE, all_headers).status_code

    def test_a_token_is_required_and_the_client_is_told_where_to_log_in(self):
        response = self.post("/mcp", INITIALIZE, {"Accept": "application/json"})
        self.assertEqual(response.status_code, 401)
        challenge = response.headers["WWW-Authenticate"]
        self.assertIn("Bearer", challenge)
        self.assertIn(f'resource_metadata="{METADATA_URL}"', challenge)

    def test_an_mcp_access_token_works(self):
        self.assertEqual(self.initialize(self.token), 200)

    def test_json_api_tokens_are_refused(self):
        _grant, refresh_token = issue_grant(self.user, "Script")
        api_access_token = refresh_tokens(refresh_token).access_token
        self.assertEqual(self.initialize(api_access_token), 401)

    def test_refresh_tokens_and_unknown_tokens_are_refused(self):
        refresh = ApiToken.objects.filter(grant=self.grant, kind="refresh").get()
        self.assertEqual(self.initialize(f"rt_{refresh.prefix}xxxxxxxxxxxxxxxx"), 401)
        self.assertEqual(self.initialize("at_" + "x" * 43), 401)
        self.assertEqual(self.initialize(""), 401)

    def test_expired_and_revoked_tokens_are_refused(self):
        _ = ApiToken.objects.filter(grant=self.grant, kind="access").update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.initialize(self.token), 401)
        _ = ApiToken.objects.filter(grant=self.grant, kind="access").update(
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        self.assertEqual(self.initialize(self.token), 200)
        end_grant(self.grant)
        self.assertEqual(self.initialize(self.token), 401)

    def test_inactive_users_are_refused(self):
        _ = User.objects.filter(id=self.user.id).update(is_active=False)
        self.assertEqual(self.initialize(self.token), 401)

    def test_using_a_token_records_when_the_grant_was_last_used(self):
        self.assertIsNone(self.grant.last_used_at)
        _ = self.initialize(self.token)
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.last_used_at)

    def test_requests_from_other_origins_are_refused(self):
        evil = {"Origin": "https://evil.example"}
        with self.assertLogs(SECURITY_LOGGER, "WARNING"):
            self.assertEqual(self.initialize(self.token, evil), 403)

    @override_settings(MCP_ALLOWED_ORIGINS=["https://inspector.example"])
    def test_allowed_origins_may_call_it_with_cors(self):
        origin = {"Origin": "https://inspector.example"}
        self.assertEqual(self.initialize(self.token, origin), 200)
        response = self.post(
            "/mcp",
            INITIALIZE,
            {
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self.token}",
                **origin,
            },
        )
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], "https://inspector.example"
        )
        self.assertIn(
            "WWW-Authenticate", response.headers["Access-Control-Expose-Headers"]
        )

    def test_unknown_hosts_are_refused(self):
        with self.assertLogs(SECURITY_LOGGER, "WARNING"):
            status = self.initialize(self.token, {"Host": "evil.example"})
        self.assertEqual(status, 421)

    @override_settings(ALLOWED_HOSTS=["tracker.example"])
    def test_allowed_hosts_are_answered(self):
        self.assertEqual(self.initialize(self.token, {"Host": "tracker.example"}), 200)
        self.assertEqual(
            self.initialize(self.token, {"Host": "tracker.example:8443"}), 200
        )


class MetadataTests(McpTestCase):
    def test_the_protected_resource_metadata_names_the_web_app_as_issuer(self):
        for path in (
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-protected-resource",
        ):
            with self.subTest(path=path):
                response = self.get(path, {"Origin": "https://app.example"})
                self.assertEqual(response.status_code, 200)
                metadata = cast(Json, response.json())
                self.assertEqual(metadata["resource"], "http://localhost:8002/mcp")
                self.assertEqual(
                    metadata["authorization_servers"], ["http://localhost:8000"]
                )
                self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    @override_settings(
        MCP_RESOURCE_URL="https://mcp.tracker.example/agents",
        OAUTH_ISSUER="https://tracker.example",
    )
    def test_the_urls_come_from_the_settings(self):
        response = self.get(
            "/.well-known/oauth-protected-resource/agents",
            {"Host": "mcp.tracker.example"},
        )
        metadata = cast(Json, response.json())
        self.assertEqual(metadata["resource"], "https://mcp.tracker.example/agents")
        self.assertEqual(metadata["authorization_servers"], ["https://tracker.example"])

    def test_the_health_check_needs_no_token(self):
        response = self.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
