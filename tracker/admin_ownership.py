"""Admin base classes that respect record ownership (see tracker/ownership.py).

Superusers see every user's records, with a "User owner" column and filter.
Any other staff account sees, and can link to, only its own records: the admin
is meant for superusers, and this keeps staff access granted by mistake from
exposing other people's data.
"""

from collections.abc import Sequence
from typing import cast, override

from django.contrib import admin
from django.contrib.admin.options import BaseModelAdmin
from django.db.models import F, Model, QuerySet
from django.db.models.fields.related import RelatedField
from django.http import HttpRequest

from accounts.http import request_user
from accounts.models import User

from .models import Application, Company, Job
from .ownership import (
    OWNER_PATHS,
    applications_for,
    companies_for,
    jobs_for,
)

# Queryset annotation holding the owner's email, for superusers' owner column.
OWNER_EMAIL = "user_owner_email"

# Every model a tracker foreign key points at, so get_field_queryset can limit
# its choices to the user's own records.
SCOPED_CHOICE_MODELS: frozenset[type[Model]] = frozenset(
    {User, Company, Job, Application}
)

type ChoiceQuerySet = (
    QuerySet[User] | QuerySet[Company] | QuerySet[Job] | QuerySet[Application]
)


class OwnershipMixin[M: Model](BaseModelAdmin[M]):
    """Limits records and foreign key choices to the user's own, unless superuser."""

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet[M]:
        queryset = super().get_queryset(request)
        user = request_user(request)
        owner_path = OWNER_PATHS[queryset.model]
        if user.is_superuser:
            # The owner's email, for the "User owner" column (one query, not one per row).
            return queryset.annotate(**{OWNER_EMAIL: F(f"{owner_path}__email")})
        return queryset.filter(**{owner_path: user})

    @override
    def get_field_queryset(
        self,
        db: None,
        db_field: RelatedField[object, object],
        request: HttpRequest | None,
    ) -> ChoiceQuerySet | None:
        """Foreign key choices: only the user's own records (and themselves as owner).

        Covers every model a tracker foreign key points at; a test checks no
        foreign key is missing from SCOPED_CHOICE_MODELS.
        """
        default = super().get_field_queryset(db, db_field, request)
        if request is None or request_user(request).is_superuser:
            return default
        user = request_user(request)
        related = db_field.related_model
        if related is User:
            return User.objects.filter(id=user.id)
        if related is Company:
            return companies_for(user)
        if related is Job:
            return jobs_for(user)
        if related is Application:
            return applications_for(user)
        return default


class OwnedModelAdmin[M: Model](OwnershipMixin[M], admin.ModelAdmin[M]):
    @admin.display(description="User owner", ordering=OWNER_EMAIL)
    def user_owner_column(self, obj: M) -> str:
        """The owner's email, annotated by get_queryset for superusers."""
        return cast(str, getattr(obj, OWNER_EMAIL, ""))

    @override
    def get_list_display(self, request: HttpRequest) -> Sequence[str]:
        columns = super().get_list_display(request)
        if request_user(request).is_superuser:
            return [*columns, "user_owner_column"]
        return columns

    @override
    def get_list_filter(self, request: HttpRequest) -> Sequence[str]:
        filters = super().get_list_filter(request)
        if request_user(request).is_superuser:
            return [*filters, OWNER_PATHS[self.model]]
        return filters

    @override
    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, str]:
        """New companies and files are owned by whoever adds them, by default."""
        initial = super().get_changeform_initial_data(request)
        if OWNER_PATHS[self.model] == "user_owner":
            _ = initial.setdefault("user_owner", str(request_user(request).id))
        return initial


class OwnedTabularInline[M: Model](OwnershipMixin[M], admin.TabularInline[M]):
    pass


class OwnedStackedInline[M: Model](OwnershipMixin[M], admin.StackedInline[M]):
    pass
