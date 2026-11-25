"""Shared helpers for the MCP server tests (not collected as tests itself).

Requests go to the real ASGI app (mcp_server.server.build_app), with the MCP
SDK's own client, through an in-process HTTP transport. They're run from the
test's thread with async_to_sync, so the tools' database work happens on the
test's connection, inside its transaction.
"""

from collections.abc import Awaitable, Callable
from typing import ClassVar, cast, override

import httpx2
from asgiref.sync import async_to_sync
from django.test import TestCase
from mcp.client import Client
from mcp.client.client import ConnectMode
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, TextContent
from starlette.applications import Starlette
from starlette.types import ASGIApp

from accounts.api_tokens import issue_mcp_grant
from accounts.models import ApiGrant, OAuthClient, User

from ..server import build_app

type Json = dict[str, object]

BASE_URL = "http://localhost:8002"


def starlette_of(app: ASGIApp) -> Starlette:
    """The Starlette app, inside the CORS middleware if it's wrapped."""
    while not isinstance(app, Starlette):
        app = cast(ASGIApp, getattr(app, "app"))  # noqa: B009
    return app


async def http[T](
    work: Callable[[httpx2.AsyncClient], Awaitable[T]],
    headers: dict[str, str] | None = None,
) -> T:
    """Run `work` with an HTTP client for a freshly built, started app."""
    app = build_app()
    starlette = starlette_of(app)
    async with (
        starlette.router.lifespan_context(starlette),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=BASE_URL,
            headers=headers,
        ) as client,
    ):
        return await work(client)


class McpTestCase(TestCase):
    """A user with an MCP grant (from an OAuth client) and an access token,
    and helpers to use the MCP server with it."""

    user: ClassVar[User]
    oauth_client: ClassVar[OAuthClient]
    grant: ClassVar[ApiGrant]
    token: ClassVar[str]
    # How the client connects: "legacy" is the initialize handshake most
    # clients use today; "auto" negotiates the newest protocol.
    mode: ConnectMode = "legacy"

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("owner@example.com", "x")
        cls.oauth_client = OAuthClient.objects.create(
            client_id="test-client",
            name="Test agent",
            redirect_uris=["http://localhost:33418/callback"],
        )
        cls.grant, pair = issue_mcp_grant(cls.user, cls.oauth_client)
        cls.token = pair.access_token

    def session[T](
        self, work: Callable[[Client], Awaitable[T]], token: str | None = None
    ) -> T:
        """Run `work` with an MCP client connected with `token` (this test
        case's access token unless given)."""

        async def connect(http_client: httpx2.AsyncClient) -> T:
            transport = streamable_http_client(
                f"{BASE_URL}/mcp", http_client=http_client
            )
            async with Client(transport, mode=self.mode, cache=None) as client:
                return await work(client)

        headers = {"Authorization": f"Bearer {token or self.token}"}
        return async_to_sync(http)(connect, headers)

    def call(self, tool: str, **arguments: object) -> CallToolResult:
        async def work(client: Client) -> CallToolResult:
            return await client.call_tool(tool, arguments)

        return self.session(work)

    def ok(self, tool: str, **arguments: object) -> Json:
        """The structured content of a tool call that must succeed."""
        result = self.call(tool, **arguments)
        self.assertFalse(result.is_error, result)
        return cast(Json, result.structured_content)

    def error(self, tool: str, **arguments: object) -> str:
        """The message of a tool call that must fail."""
        result = self.call(tool, **arguments)
        self.assertTrue(result.is_error, result)
        content = result.content[0]
        assert isinstance(content, TextContent)
        return content.text

    def tool_names(self, token: str | None = None) -> set[str]:
        async def work(client: Client) -> set[str]:
            return {tool.name for tool in (await client.list_tools()).tools}

        return self.session(work, token)

    def post(
        self, path: str, body: object = None, headers: dict[str, str] | None = None
    ) -> httpx2.Response:
        """A raw POST to the app."""

        async def work(client: httpx2.AsyncClient) -> httpx2.Response:
            return await client.post(path, json=body, headers=headers)

        return async_to_sync(http)(work)

    def get(self, path: str, headers: dict[str, str] | None = None) -> httpx2.Response:
        async def work(client: httpx2.AsyncClient) -> httpx2.Response:
            return await client.get(path, headers=headers)

        return async_to_sync(http)(work)


def items(page: Json) -> list[Json]:
    return cast(list[Json], page["items"])


def names(page: Json, key: str = "name") -> list[str]:
    return [cast(str, item[key]) for item in items(page)]
