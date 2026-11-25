"""Turning failures into the API's JSON errors: {"detail": ..., "errors": ...}."""

from collections.abc import Mapping, Sequence
from typing import cast, final

from django.forms import BaseForm
from django.http import QueryDict

INVALID_FIELDS = "Some fields aren't valid."
# Parts of a pydantic error location that say where a value came from rather
# than name the field, e.g. ("body", "payload", "title") is just "title".
SOURCE_PARTS = frozenset({"body", "query", "path", "payload", "params"})

type FieldErrorMap = dict[str, list[str]]


@final
class FieldErrors(Exception):
    """Invalid fields, answered with a 422 (see api/urls.py)."""

    def __init__(self, errors: FieldErrorMap) -> None:
        super().__init__(errors)
        self.errors = errors


def form_errors(
    form: BaseForm, renames: Mapping[str, str] | None = None
) -> FieldErrorMap:
    """A form's errors by API field name; errors not tied to a field are
    under "non_field_errors"."""
    names = {"__all__": "non_field_errors", **(renames or {})}
    return {
        names.get(field, field): [
            message for error in errors for message in error.messages
        ]
        for field, errors in form.errors.as_data().items()
    }


def schema_errors(errors: Sequence[Mapping[str, object]]) -> FieldErrorMap:
    """Django Ninja's (pydantic's) validation errors by field name."""
    found: FieldErrorMap = {}
    for error in errors:
        location = error.get("loc", ())
        parts = (
            [str(part) for part in cast(Sequence[object], location)]
            if isinstance(location, (list, tuple))
            else []
        )
        field = ".".join(part for part in parts if part not in SOURCE_PARTS)
        found.setdefault(field or "body", []).append(str(error.get("msg", "Invalid.")))
    return found


def form_data(values: Mapping[str, str | list[str]]) -> QueryDict:
    """Values as the QueryDict a Django form reads (lists as repeated keys)."""
    data = QueryDict(mutable=True)
    for key, value in values.items():
        if isinstance(value, list):
            data.setlist(key, value)
        else:
            data[key] = value
    return data
