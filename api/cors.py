"""CORS for the public OAuth endpoints, so browser-based MCP clients can use
them: the authorization server metadata, client registration and the token
endpoint.

Any origin may call them: they don't use cookies, so a page on another site
gets nothing it couldn't get from its own server (the token endpoint needs a
refresh token or an authorization code, and its PKCE verifier).
"""

from collections.abc import Callable
from typing import final

from django.http import HttpRequest, HttpResponse

PUBLIC_PATHS = frozenset(
    {
        "/.well-known/oauth-authorization-server",
        "/api/v1/oauth/register",
        "/api/v1/oauth/token",
    }
)


@final
class PublicCorsMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path not in PUBLIC_PATHS:
            return self.get_response(request)
        if request.method == "OPTIONS":
            # A preflight request: answer it here.
            response = HttpResponse(status=204)
            response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = (
                "Content-Type, MCP-Protocol-Version"
            )
            response["Access-Control-Max-Age"] = "86400"
        else:
            response = self.get_response(request)
        response["Access-Control-Allow-Origin"] = "*"
        # So a browser client can see how long to wait after a 429.
        response["Access-Control-Expose-Headers"] = "Retry-After"
        return response
