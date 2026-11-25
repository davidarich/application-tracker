from typing import final

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import UserChangeAdminForm, UserCreationAdminForm
from .models import User

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
