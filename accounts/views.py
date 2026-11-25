import uuid
from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.utils.cache import add_never_cache_headers
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .api_tokens import Audience, active_grants_for, issue_grant, revoke_grant
from .forms import ApiTokenForm, AvatarForm, ProfileForm
from .http import request_user
from .oauth import (
    OAuthError,
    RedirectError,
    issue_code,
    parse_authorize,
    server_metadata,
)

# Session key holding a just-created refresh token until the API tokens page
# shows it (once: it's removed as it's shown, and only its hash is stored).
NEW_TOKEN_SESSION_KEY = "new_api_token"


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    """Let the logged-in user edit their own details."""
    user = request_user(request)
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated.")
            # Redirect after a successful POST so a refresh doesn't resubmit it.
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=user)
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def api_tokens(request: HttpRequest) -> HttpResponse:
    """The user's API tokens (OAuth 2.0 grants), with forms to create and
    revoke them. A just-created refresh token is shown here once."""
    user = request_user(request)
    new_api_token = cast(
        dict[str, str] | None, request.session.pop(NEW_TOKEN_SESSION_KEY, None)
    )
    response = render(
        request,
        "accounts/api_tokens.html",
        {
            "token_form": ApiTokenForm(),
            "api_grants": active_grants_for(user),
            "connected_apps": active_grants_for(user, Audience.MCP),
            "new_api_token": new_api_token,
        },
    )
    if new_api_token is not None:
        # The page shows a refresh token: keep it out of the browser's cache
        # (and its back button), as RFC 6749 asks of token responses.
        add_never_cache_headers(response)
    return response


@login_required
@require_POST
def api_token_create(request: HttpRequest) -> HttpResponse:
    """Create an API grant; the API tokens page shows its refresh token once,
    after the redirect."""
    user = request_user(request)
    form = ApiTokenForm(request.POST)
    if not form.is_valid():
        messages.error(request, str(form.errors["name"][0]))
        return redirect("accounts:api_tokens")
    grant, token = issue_grant(user, cast(str, form.cleaned_data["name"]))
    request.session[NEW_TOKEN_SESSION_KEY] = {"name": grant.name, "token": token}
    return redirect("accounts:api_tokens")


@login_required
@require_POST
def api_token_revoke(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Revoke one of the user's API grants (all its tokens), including a
    connected app's; anyone else's is a 404."""
    grant = revoke_grant(request_user(request), pk)
    if grant is None:
        raise Http404("No such token.")
    if grant.audience == Audience.MCP.value:
        messages.success(request, f"Disconnected {grant.name}.")
    else:
        messages.success(request, f"Revoked the token {grant.name}.")
    return redirect("accounts:api_tokens")


@require_GET
def oauth_server_metadata(_request: HttpRequest) -> HttpResponse:
    """The OAuth 2.0 authorization server metadata (RFC 8414), which MCP
    clients read to find the endpoints below (see accounts/oauth.py)."""
    return JsonResponse(server_metadata())


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def oauth_authorize(request: HttpRequest) -> HttpResponse:
    """The OAuth 2.0 authorization endpoint: asks the logged-in user whether
    an app (an MCP client) may use their account through the MCP server, and
    sends them back to the app with a one-time code if they allow it.

    The consent form posts the request's parameters back, and they're
    checked again: nothing from the GET is trusted on the POST."""
    params = request.POST if request.method == "POST" else request.GET
    try:
        authorize = parse_authorize({key: params.get(key, "") for key in params})
    except OAuthError as error:
        # Not the client's redirect URI (or no client): never redirect.
        return render(
            request,
            "accounts/oauth_error.html",
            {"description": error.description},
            status=400,
        )
    except RedirectError as error:
        return HttpResponseRedirect(error.redirect_url())
    if request.method == "GET":
        return render(
            request, "accounts/oauth_authorize.html", {"authorize": authorize}
        )
    if request.POST.get("decision") != "allow":
        return HttpResponseRedirect(
            authorize.redirect_with(
                {
                    "error": "access_denied",
                    "error_description": "The user declined to connect the app.",
                }
            )
        )
    code = issue_code(request_user(request), authorize)
    return HttpResponseRedirect(authorize.redirect_with({"code": code}))


@login_required
@require_POST
def avatar_upload(request: HttpRequest) -> HttpResponse:
    """Replace the user's profile photo with an uploaded image."""
    user = request_user(request)
    form = AvatarForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, str(form.errors["photo"][0]))
        return redirect("accounts:profile")
    photo = cast(ContentFile, form.cleaned_data["photo"])
    old_name = user.avatar.name
    user.avatar.save(photo.name or "avatar.webp", photo, save=True)
    if old_name and old_name != user.avatar.name:
        default_storage.delete(old_name)  # don't leave the old photo behind
    messages.success(request, "Your photo has been updated.")
    return redirect("accounts:profile")


@login_required
@require_POST
def avatar_remove(request: HttpRequest) -> HttpResponse:
    """Remove the user's profile photo (and its file)."""
    user = request_user(request)
    if user.avatar:
        user.avatar.delete(save=True)
        messages.success(request, "Your photo has been removed.")
    return redirect("accounts:profile")


@login_required
def avatar(request: HttpRequest) -> FileResponse:
    """The logged-in user's own profile photo (there's no way to ask for anyone else's)."""
    user = request_user(request)
    if not user.avatar:
        raise Http404("No photo.")
    try:
        handle = user.avatar.open("rb")
    except FileNotFoundError:
        raise Http404("The photo is missing from storage.") from None
    response = FileResponse(handle, content_type="image/webp")
    # Each upload gets a new file name (and the page links include it), so the
    # browser can keep this for a while; "private" keeps shared caches out.
    response["Cache-Control"] = "private, max-age=86400"
    return response
