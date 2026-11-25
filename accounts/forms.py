"""Forms for logging in and for managing users in the admin."""

from typing import ClassVar, cast, final

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    UserChangeForm,
    UserCreationForm,
)
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile

from .avatars import process_avatar
from .models import User


@final
class EmailAuthenticationForm(AuthenticationForm):
    """The login form, asking for an email address instead of a username.

    The field keeps the name "username", which Django's login view and
    authentication backend expect; it holds the email address.
    """

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )
    error_messages: dict[str, str] = {  # noqa: RUF012 (Django's API)
        "invalid_login": (
            "Please enter a correct email and password. Note that the password is case-sensitive."
        ),
        "inactive": "This account is inactive.",
    }


@final
class UserCreationAdminForm(UserCreationForm):
    """The admin's "Add user" form, for a user identified by email."""

    @final
    class Meta:
        model = User
        fields: ClassVar[list[str]] = [
            "email",
            "first_name",
            "middle_name",
            "last_name",
            "preferred_name",
            "phone_number",
        ]


@final
class UserChangeAdminForm(UserChangeForm):
    @final
    class Meta:
        model = User
        fields = "__all__"


@final
class ProfileForm(forms.ModelForm):
    """A user editing their own details (not their email or password)."""

    @final
    class Meta:
        model = User
        fields: ClassVar[list[str]] = [
            "first_name",
            "middle_name",
            "last_name",
            "preferred_name",
            "phone_number",
        ]
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "middle_name": forms.TextInput(attrs={"autocomplete": "additional-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "preferred_name": forms.TextInput(attrs={"autocomplete": "nickname"}),
            "phone_number": forms.TextInput(
                attrs={"type": "tel", "autocomplete": "tel"}
            ),
        }
        # The model's help text is written for admins editing someone else.
        help_texts: ClassVar[dict[str, str]] = {
            "preferred_name": (
                "What you like to be called, if not your first name (e.g. Bill for William)."
            ),
        }


@final
class AvatarForm(forms.Form):
    """Upload a profile photo; cleaned to a square WebP (see accounts/avatars.py)."""

    photo = forms.FileField(
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/jpeg,image/png,image/gif,image/webp"}
        ),
        error_messages={"required": "Choose a photo to upload."},
    )

    def clean_photo(self) -> ContentFile:
        return process_avatar(cast(UploadedFile, self.cleaned_data["photo"]))


@final
class ApiTokenForm(forms.Form):
    """The name of a new API grant: what will use it. accounts/api_tokens.py
    creates the grant and its first refresh token."""

    name = forms.CharField(
        max_length=100,
        strip=True,
        error_messages={"required": "Give the token a name, e.g. Browser extension."},
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. Browser extension", "autocomplete": "off"}
        ),
    )
