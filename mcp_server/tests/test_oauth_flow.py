"""The whole flow an MCP client goes through: register, have the user allow
it on the consent page, swap the code for tokens, call a tool, refresh, and
lose access when the user disconnects the app."""

import secrets
from typing import cast
from urllib.parse import parse_qs, urlencode, urlsplit

from django.urls import reverse
from mcp.client import Client
from mcp_types import CallToolResult

from accounts.models import ApiGrant, User
from accounts.oauth import s256
from tracker.models import Company

from .helpers import Json, McpTestCase

REDIRECT = "http://127.0.0.1:40123/callback"
FORM = "application/x-www-form-urlencoded"


class OAuthFlowTests(McpTestCase):
    def token_request(self, data: dict[str, str]) -> Json:
        response = self.client.post(
            "/api/v1/oauth/token", urlencode(data), content_type=FORM
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        return cast(Json, response.json())

    def test_connect_use_refresh_and_disconnect(self):
        user = User.objects.create_user("agent-user@example.com", "x")
        _ = Company.objects.create(user_owner=user, name="Acme")

        # 1. The client finds where to log in.
        resource = cast(
            Json, self.get("/.well-known/oauth-protected-resource/mcp").json()
        )
        issuer = cast(list[str], resource["authorization_servers"])[0]
        server = cast(
            Json, self.client.get("/.well-known/oauth-authorization-server").json()
        )
        self.assertEqual(server["issuer"], issuer)

        # 2. It registers.
        registered = self.client.post(
            "/api/v1/oauth/register",
            {"client_name": "Flow Agent", "redirect_uris": [REDIRECT]},
            content_type="application/json",
        )
        client_id = cast(str, cast(Json, registered.json())["client_id"])

        # 3. The user allows it on the consent page.
        verifier = secrets.token_urlsafe(48)
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "state": "s1",
            "code_challenge": s256(verifier),
            "code_challenge_method": "S256",
            "resource": cast(str, resource["resource"]),
        }
        self.client.force_login(user)
        authorize = reverse("accounts:oauth_authorize")
        self.assertContains(
            self.client.get(authorize + "?" + urlencode(params)), "Flow Agent"
        )
        response = self.client.post(authorize, {**params, "decision": "allow"})
        query = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(query["state"], ["s1"])
        code = query["code"][0]

        # 4. It swaps the code for tokens and uses the MCP server.
        tokens = self.token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": cast(str, resource["resource"]),
            }
        )

        async def list_companies(client: Client) -> CallToolResult:
            return await client.call_tool("list_companies", {})

        result = self.session(list_companies, cast(str, tokens["access_token"]))
        self.assertFalse(result.is_error)
        page = cast(Json, result.structured_content)
        self.assertEqual(cast(list[Json], page["items"])[0]["name"], "Acme")

        # 5. It refreshes (with its client_id) and keeps working.
        refreshed = self.token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": cast(str, tokens["refresh_token"]),
                "client_id": client_id,
            }
        )
        access_token = cast(str, refreshed["access_token"])
        self.assertFalse(self.session(list_companies, access_token).is_error)

        # 6. The user sees it under Connected apps and disconnects it.
        grant = ApiGrant.objects.get(user=user)
        page_html = self.client.get(reverse("accounts:api_tokens")).content.decode()
        self.assertIn("Flow Agent", page_html[page_html.index('id="connected-apps"') :])
        _ = self.client.post(reverse("accounts:api_token_revoke", args=[grant.id]))
        status = self.post(
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
        ).status_code
        self.assertEqual(status, 401)
