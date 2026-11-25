"""The project's user model: people log in with their email address."""

import uuid
from datetime import datetime
from typing import ClassVar, cast, override

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from .fields import PHONE_NUMBER_EXAMPLE, PhoneNumberField


def normalize_email(email: str) -> str:
    """Emails are matched case-insensitively, so they're stored lowercased."""
    return BaseUserManager.normalize_email(email).strip().lower()


def join_names(*names: str) -> str:
    """Join name parts with single spaces, skipping blank or whitespace-only ones."""
    return " ".join(name.strip() for name in names if name.strip())


def avatar_upload_path(instance: models.Model, _filename: str) -> str:
    """Store profile photos as avatars/<user id>/<random id>.webp: a new name
    for every upload, so browsers never show a stale cached photo. (The
    uploaded file's own name is ignored: photos are always re-encoded to WebP.)"""
    return f"avatars/{cast(User, instance).id}/{uuid.uuid4().hex}.webp"


class UserManager(BaseUserManager["User"]):
    use_in_migrations: bool = True

    def create_user(
        self, email: str, password: str | None = None, **fields: object
    ) -> "User":
        """Create a user. Without a password, the account can't log in until one is set."""
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=normalize_email(email), **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str, password: str | None = None, **fields: object
    ) -> "User":
        _ = fields.setdefault("is_staff", True)
        _ = fields.setdefault("is_superuser", True)
        if fields["is_staff"] is not True or fields["is_superuser"] is not True:
            raise ValueError(
                "A superuser must have is_staff=True and is_superuser=True."
            )
        return self.create_user(email, password, **fields)

    @override
    def get_by_natural_key(self, username: str) -> "User":
        """Look a user up by email, ignoring case (used by login)."""
        return self.get(email__iexact=username)


class User(AbstractBaseUser, PermissionsMixin):
    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    email: models.EmailField[str] = models.EmailField(
        "email address",
        unique=True,
        error_messages={"unique": "A user with that email address already exists."},
    )
    first_name: models.CharField[str] = models.CharField(max_length=150)
    middle_name: models.CharField[str] = models.CharField(max_length=150, blank=True)
    last_name: models.CharField[str] = models.CharField(max_length=150)
    preferred_name: models.CharField[str] = models.CharField(
        max_length=150,
        blank=True,
        help_text="What they like to be called, if not their first name (e.g. Bill for William).",
    )
    phone_number: models.CharField[str] = PhoneNumberField(
        max_length=20,
        help_text=f"Include the country code, e.g. {PHONE_NUMBER_EXAMPLE}.",
    )
    # Profile photo, always a 256x256 WebP (see accounts/avatars.py). Served
    # only to its owner by accounts.views.avatar, never as public media.
    avatar: models.ImageField = models.ImageField(
        "photo", upload_to=avatar_upload_path, blank=True
    )
    is_staff: models.BooleanField[bool] = models.BooleanField(
        "staff status",
        default=False,
        help_text="Whether the user can log into the admin site.",
    )
    # The stub types AbstractBaseUser.is_active as a loose union so subclasses
    # can add a real field, which a strict override check can't express.
    is_active: models.BooleanField[bool] = models.BooleanField(  # pyright: ignore[reportIncompatibleVariableOverride]
        "active",
        default=True,
        help_text="Unselect this instead of deleting accounts.",
    )
    date_joined: models.DateTimeField[datetime] = models.DateTimeField(
        "date joined", default=timezone.now
    )

    # A custom manager always "overrides" Model.objects in the stubs (Django's
    # documented pattern for custom users).
    objects: ClassVar[UserManager] = UserManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    EMAIL_FIELD: ClassVar[str] = "email"
    USERNAME_FIELD: ClassVar[str] = "email"
    # Asked for by `createsuperuser`, besides the email and password.
    REQUIRED_FIELDS: list[str] = ["first_name", "last_name", "phone_number"]

    class Meta:
        ordering: ClassVar[list[str]] = ["email"]

    @override
    def clean(self) -> None:
        super().clean()
        self.email = normalize_email(self.email)

    def get_full_name(self) -> str:
        """First, middle (if any) and last name, separated by spaces."""
        return join_names(self.first_name, self.middle_name, self.last_name)

    def get_short_name(self) -> str:
        """The name to greet them by: their preferred name, else their first name."""
        return self.preferred_name.strip() or self.first_name.strip()

    def get_display_name(self) -> str:
        """Their name as shown in the app: preferred (else first) name, middle
        initial if they have a middle name, and last name, e.g. "Bill J. Smith"."""
        middle = self.middle_name.strip()
        middle_initial = f"{middle[0].upper()}." if middle else ""
        return join_names(self.get_short_name(), middle_initial, self.last_name)


class ApiGrant(models.Model):
    """A user's permission for one program (e.g. a browser extension) to use
    the JSON API, created on the API tokens page.

    It's an OAuth 2.0 refresh token grant: the program is given a refresh
    token, which it swaps at the token endpoint for a short-lived access token
    (sent with every API request) and a new refresh token. Revoking the grant
    ends all of its tokens. See accounts/api_tokens.py.
    """

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    user: models.ForeignKey[User] = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="api_grants"
    )
    name: models.CharField[str] = models.CharField(
        max_length=100, help_text="What uses it, e.g. Browser extension."
    )
    created_at: models.DateTimeField[datetime] = models.DateTimeField(auto_now_add=True)
    last_used_at: models.DateTimeField[datetime | None] = models.DateTimeField(
        null=True, blank=True
    )
    # A revoked grant no longer works (its tokens are deleted); the row is
    # kept so the admin shows its history.
    revoked_at: models.DateTimeField[datetime | None] = models.DateTimeField(
        null=True, blank=True
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name: ClassVar[str] = "API grant"

    @override
    def __str__(self) -> str:
        return self.name


class ApiToken(models.Model):
    """An access or refresh token of an ApiGrant.

    Only a SHA-256 hash of the token is stored; the token itself is given out
    once. `prefix`, its first characters, finds the row.
    """

    class Kind(models.TextChoices):
        ACCESS = "access"  # sent with API requests; expires after minutes
        REFRESH = "refresh"  # swapped for new tokens; each works once

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    grant: models.ForeignKey[ApiGrant] = models.ForeignKey(
        ApiGrant, on_delete=models.CASCADE, related_name="tokens"
    )
    kind: models.CharField[str] = models.CharField(max_length=10, choices=Kind.choices)
    prefix: models.CharField[str] = models.CharField(max_length=12, unique=True)
    key_hash: models.CharField[str] = models.CharField(max_length=64)
    created_at: models.DateTimeField[datetime] = models.DateTimeField(auto_now_add=True)
    expires_at: models.DateTimeField[datetime] = models.DateTimeField(db_index=True)
    # Refresh tokens: when it was swapped. A used one sent again means it may
    # have been copied, so the whole grant is revoked.
    used_at: models.DateTimeField[datetime | None] = models.DateTimeField(
        null=True, blank=True
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        verbose_name: ClassVar[str] = "API token"

    @override
    def __str__(self) -> str:
        return f"{ApiToken.Kind(self.kind).label} token {self.prefix}…"
