from typing import final, override

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import QuerySet
from django.http import HttpRequest

from .api_tokens import end_grant
from .forms import UserChangeAdminForm, UserCreationAdminForm
from .models import ApiGrant, ApiToken, User

# The shape of ModelAdmin fieldsets: (title, {"fields": (...), ...}) pairs.
type Fieldsets = tuple[tuple[str | None, dict[str, tuple[str, ...]]], ...]


@admin.register(User)
@final
class UserAdmin(BaseUserAdmin):
    """Django's user admin, adapted to users identified by email."""

    form = UserChangeAdminForm
    add_form = UserCreationAdminForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "middle_name",
                    "last_name",
                    "preferred_name",
                    "phone_number",
                    "avatar",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets: Fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "middle_name",
                    "last_name",
                    "preferred_name",
                    "phone_number",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = (
        "email",
        "first_name",
        "middle_name",
        "last_name",
        "preferred_name",
        "phone_number",
    )
    ordering = ("email",)
    readonly_fields = ("last_login", "date_joined")


@final
class ApiTokenInline(admin.TabularInline[ApiToken]):
    model = ApiToken
    fields = ("kind", "prefix", "created_at", "expires_at", "used_at")
    readonly_fields = fields
    extra = 0
    can_delete = False

    @override
    def has_add_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(ApiGrant)
@final
class ApiGrantAdmin(admin.ModelAdmin[ApiGrant]):
    """API grants, to see what's in use and revoke access. Grants are made on
    the API tokens page (the only place a refresh token is ever shown)."""

    list_display = ("name", "user", "created_at", "last_used_at", "revoked_at")
    list_filter = (("revoked_at", admin.EmptyFieldListFilter),)
    search_fields = ("name", "user__email")
    readonly_fields = ("id", "user", "name", "created_at", "last_used_at", "revoked_at")
    inlines = (ApiTokenInline,)
    actions = ("revoke",)

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.action(description="Revoke selected grants")
    def revoke(self, request: HttpRequest, queryset: QuerySet[ApiGrant]) -> None:
        grants = list(queryset.filter(revoked_at__isnull=True))
        for grant in grants:
            end_grant(grant)
        count = len(grants)
        self.message_user(request, f"Revoked {count} grant{'s' if count != 1 else ''}.")
