"""The JSON API, served at /api/v1/.

The web app includes these URLs alongside its own; a process started with
DJANGO_ROLE=api serves only these (see app_tracker/settings.py), so the API
can run in a container of its own.
"""

from django.db import IntegrityError
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import path
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, ValidationError

from .auth import TokenAuth, refusal
from .errors import INVALID_FIELDS, FieldErrors, schema_errors
from .routers import companies, jobs, oauth, skills

DESCRIPTION = (
    "Add and change your jobs, companies and skills.\n\n"
    + "**Authentication is OAuth 2.0** (the refresh token grant). Create a "
    + "refresh token on your API tokens page, then exchange it at "
    + "`POST /api/v1/oauth/token` for an access token, which lasts 15 minutes, "
    + "and a new refresh token (each refresh token works once). Send the access "
    + "token with every other request: `Authorization: Bearer <access token>`.\n\n"
    + "Errors are JSON: `detail` says what went wrong and, for invalid fields "
    + "(422), `errors` lists each field's messages. The token endpoint uses "
    + "OAuth's error format instead: `error` and `error_description`."
)

api = NinjaAPI(
    title="Job Tracker API",
    version="1",
    description=DESCRIPTION,
    auth=TokenAuth(),
    urls_namespace="api",
)
api.add_router("/oauth", oauth.router)
api.add_router("/companies", companies.router)
api.add_router("/jobs", jobs.router)
api.add_router("/skills", skills.router)


@api.exception_handler(AuthenticationError)
def unauthorized(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
    """No usable access token: a 401 with a WWW-Authenticate header (RFC 6750)."""
    message, challenge = refusal(request)
    response = api.create_response(request, {"detail": message}, status=exc.status_code)
    response["WWW-Authenticate"] = challenge
    return response


@api.exception_handler(FieldErrors)
def invalid_fields(request: HttpRequest, exc: FieldErrors) -> HttpResponse:
    return api.create_response(
        request, {"detail": INVALID_FIELDS, "errors": exc.errors}, status=422
    )


@api.exception_handler(ValidationError)
def invalid_request(request: HttpRequest, exc: ValidationError) -> HttpResponse:
    """The JSON didn't have the expected shape (missing fields, wrong types)."""
    return api.create_response(
        request,
        {"detail": INVALID_FIELDS, "errors": schema_errors(exc.errors)},
        status=422,
    )


@api.exception_handler(Http404)
def not_found(request: HttpRequest, exc: Http404) -> HttpResponse:
    return api.create_response(
        request, {"detail": str(exc) or "Not found."}, status=404
    )


@api.exception_handler(IntegrityError)
def conflict(request: HttpRequest, _exc: IntegrityError) -> HttpResponse:
    """A unique name taken by a request saved at the same moment."""
    return api.create_response(
        request,
        {"detail": "That clashes with a record saved at the same time. Try again."},
        status=409,
    )


urlpatterns = [path("api/v1/", api.urls)]
