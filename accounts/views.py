from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import AvatarForm, ProfileForm
from .http import request_user


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
