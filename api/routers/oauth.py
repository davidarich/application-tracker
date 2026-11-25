"""The OAuth 2.0 token endpoint: the refresh token grant (RFC 6749 section 6).

    POST /api/v1/oauth/token
    Content-Type: application/x-www-form-urlencoded

    grant_type=refresh_token&refresh_token=rt_...

answers with a new access token and a new refresh token (the one sent stops
working). Errors use OAuth's own format, {"error": ..., "error_description":
...}, rather than the rest of the API's. Clients are public (no client ID or
secret): the refresh token, from the API tokens page, is the credential.
"""

from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Router, Schema

from accounts.api_tokens import RefreshError, refresh_tokens

router = Router(tags=["OAuth"])

FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


class TokenOut(Schema):
    access_token: str
    token_type: str  # always "Bearer"
    expires_in: int  # seconds the access token lasts
    refresh_token: str  # use this one next time: each works once


class OAuthErrorOut(Schema):
    # invalid_request, invalid_grant or unsupported_grant_type
    error: str
    error_description: str


def no_store(response: HttpResponse) -> HttpResponse:
    """Tokens mustn't be cached (RFC 6749 section 5.1)."""
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def oauth_error(error: str, description: str) -> HttpResponse:
    return no_store(
        JsonResponse({"error": error, "error_description": description}, status=400)
    )


REQUEST_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            FORM_CONTENT_TYPE: {
                "schema": {
                    "type": "object",
                    "required": ["grant_type", "refresh_token"],
                    "properties": {
                        "grant_type": {"type": "string", "enum": ["refresh_token"]},
                        "refresh_token": {"type": "string"},
                    },
                }
            }
        },
    }
}


@router.post(
    "/token",
    auth=None,
    response={200: TokenOut, 400: OAuthErrorOut},
    openapi_extra=REQUEST_BODY,
)
def token(request: HttpRequest) -> HttpResponse:
    """Swap a refresh token for a new access token (lasting `expires_in`
    seconds) and a new refresh token. Each refresh token works once: sending
    a used one again revokes its access, in case it was copied."""
    if request.content_type != FORM_CONTENT_TYPE:
        return oauth_error(
            "invalid_request",
            "Send the parameters form-encoded (" + FORM_CONTENT_TYPE + ").",
        )
    grant_type = request.POST.get("grant_type", "")
    if not grant_type:
        return oauth_error("invalid_request", "grant_type is required.")
    if grant_type != "refresh_token":
        return oauth_error(
            "unsupported_grant_type", "Only the refresh_token grant is supported."
        )
    refresh_token = request.POST.get("refresh_token", "").strip()
    if not refresh_token:
        return oauth_error("invalid_request", "refresh_token is required.")
    try:
        pair = refresh_tokens(refresh_token)
    except RefreshError as error:
        return oauth_error("invalid_grant", str(error))
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
