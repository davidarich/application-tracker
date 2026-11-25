"""The OAuth 2.0 endpoints: the token endpoint and client registration.

    POST /api/v1/oauth/token
    Content-Type: application/x-www-form-urlencoded

    grant_type=refresh_token&refresh_token=rt_...

answers with a new access token and a new refresh token (the one sent stops
working). For the JSON API, clients are public with no client ID: the refresh
token, from the API tokens page, is the credential.

MCP clients (accounts/oauth.py) register at POST /api/v1/oauth/register,
then swap an authorization code from the consent page with
grant_type=authorization_code (with code, redirect_uri, client_id and the
PKCE code_verifier), and send their client_id when refreshing too.

Errors use OAuth's own format, {"error": ..., "error_description": ...},
rather than the rest of the API's.

Both endpoints are rate limited (accounts/rate_limits.py): too many requests
are answered with 429, error "too_many_requests" and a Retry-After header.
"""

import json
from typing import cast

from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Router, Schema

from accounts.api_tokens import RefreshError, TokenPair, refresh_tokens
from accounts.oauth import (
    CodeExchange,
    OAuthError,
    client_information,
    exchange_code,
    register_client,
)
from accounts.rate_limits import check_rate_limit

router = Router(tags=["OAuth"])

FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


class TokenOut(Schema):
    access_token: str
    token_type: str  # always "Bearer"
    expires_in: int  # seconds the access token lasts
    refresh_token: str  # use this one next time: each works once


class OAuthErrorOut(Schema):
    # e.g. invalid_request, invalid_grant or unsupported_grant_type; for a
    # 429, too_many_requests
    error: str
    error_description: str


def no_store(response: HttpResponse) -> HttpResponse:
    """Tokens mustn't be cached (RFC 6749 section 5.1)."""
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def oauth_error(error: str, description: str, status: int = 400) -> HttpResponse:
    return no_store(
        JsonResponse({"error": error, "error_description": description}, status=status)
    )


def rate_limited(request: HttpRequest, scope: str) -> HttpResponse | None:
    """A 429 answer if `request` is over `scope`'s rate limit, else None."""
    wait = check_rate_limit(request, scope)
    if wait is None:
        return None
    response = oauth_error(
        "too_many_requests",
        f"Too many requests. Try again in {wait} seconds.",
        status=429,
    )
    response["Retry-After"] = str(wait)
    return response


def token_response(pair: TokenPair) -> HttpResponse:
    return no_store(
        JsonResponse(
            {
                "access_token": pair.access_token,
                "token_type": "Bearer",
                "expires_in": pair.expires_in,
                "refresh_token": pair.refresh_token,
            }
        )
    )


REQUEST_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            FORM_CONTENT_TYPE: {
                "schema": {
                    "type": "object",
                    "required": ["grant_type"],
                    "properties": {
                        "grant_type": {
                            "type": "string",
                            "enum": ["refresh_token", "authorization_code"],
                        },
                        "refresh_token": {
                            "type": "string",
                            "description": "refresh_token grant.",
                        },
                        "client_id": {
                            "type": "string",
                            "description": (
                                "MCP clients: authorization_code grant, and "
                                + "refresh_token for their grants."
                            ),
                        },
                        "code": {
                            "type": "string",
                            "description": "authorization_code grant.",
                        },
                        "redirect_uri": {
                            "type": "string",
                            "description": "authorization_code grant.",
                        },
                        "code_verifier": {
                            "type": "string",
                            "description": "authorization_code grant (PKCE).",
                        },
                        "resource": {
                            "type": "string",
                            "description": "Optional: the MCP server's URL.",
                        },
                    },
                }
            }
        },
    }
}


@router.post(
    "/token",
    auth=None,
    response={200: TokenOut, 400: OAuthErrorOut, 429: OAuthErrorOut},
    openapi_extra=REQUEST_BODY,
)
def token(request: HttpRequest) -> HttpResponse:
    """Swap a refresh token (or, for MCP clients, an authorization code) for
    a new access token (lasting `expires_in` seconds) and a new refresh
    token. Each refresh token works once: sending a used one again revokes
    its access, in case it was copied. Rate limited per client address."""
    if limited := rate_limited(request, "token"):
        return limited
    if request.content_type != FORM_CONTENT_TYPE:
        return oauth_error(
            "invalid_request",
            "Send the parameters form-encoded (" + FORM_CONTENT_TYPE + ").",
        )
    grant_type = request.POST.get("grant_type", "")
    if not grant_type:
        return oauth_error("invalid_request", "grant_type is required.")
    if grant_type == "authorization_code":
        return authorization_code_grant(request)
    if grant_type != "refresh_token":
        return oauth_error(
            "unsupported_grant_type",
            "Only the refresh_token and authorization_code grants are supported.",
        )
    refresh_token = request.POST.get("refresh_token", "").strip()
    if not refresh_token:
        return oauth_error("invalid_request", "refresh_token is required.")
    client_id = request.POST.get("client_id", "").strip()
    try:
        pair = refresh_tokens(refresh_token, client_id)
    except RefreshError as error:
        return oauth_error("invalid_grant", str(error))
    return token_response(pair)


def authorization_code_grant(request: HttpRequest) -> HttpResponse:
    values = {
        name: request.POST.get(name, "").strip()
        for name in ("code", "redirect_uri", "client_id", "code_verifier")
    }
    for name, value in values.items():
        if not value:
            return oauth_error("invalid_request", f"{name} is required.")
    try:
        pair = exchange_code(
            CodeExchange(
                code=values["code"],
                client_id=values["client_id"],
                redirect_uri=values["redirect_uri"],
                code_verifier=values["code_verifier"],
                resource=request.POST.get("resource", "").strip(),
            )
        )
    except OAuthError as error:
        return oauth_error(error.error, error.description)
    return token_response(pair)


REGISTRATION_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["redirect_uris"],
                    "properties": {
                        "redirect_uris": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "client_name": {"type": "string"},
                        "grant_types": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "response_types": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                }
            }
        },
    }
}


class ClientOut(Schema):
    client_id: str
    client_id_issued_at: int
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str  # always "none": clients are public


@router.post(
    "/register",
    auth=None,
    response={201: ClientOut, 400: OAuthErrorOut, 429: OAuthErrorOut},
    openapi_extra=REGISTRATION_BODY,
)
def register(request: HttpRequest) -> HttpResponse:
    """Register an MCP client (dynamic client registration, RFC 7591). It
    gets a client_id and no secret: clients are public, and use the
    authorization code grant with PKCE. Redirect URIs must be https, or http
    on localhost. Rate limited per client address, and in total."""
    if limited := rate_limited(request, "register"):
        return limited
    try:
        metadata = cast(object, json.loads(request.body or b"null"))
    except ValueError:
        metadata = None
    if not isinstance(metadata, dict):
        return oauth_error(
            "invalid_client_metadata", "Send the client metadata as a JSON object."
        )
    try:
        client = register_client(cast(dict[str, object], metadata))
    except OAuthError as error:
        return oauth_error(error.error, error.description)
    return no_store(JsonResponse(client_information(client), status=201))
