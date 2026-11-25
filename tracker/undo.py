"""Undo for soft deletes: the last one is remembered in the session, and its
"Deleted …" message offers an Undo button (see layouts/app.html and
tracker.views.undo_delete, which restores the record after re-checking that
it belongs to the user). Each undo can be used once."""

import uuid

from django.contrib import messages
from django.http import HttpRequest

UNDO_SESSION_KEY = "undo_delete"


def offer_undo(
    request: HttpRequest, kind: str, record_id: uuid.UUID, label: str
) -> None:
    """Remember a soft delete for undo, and say it happened (with an Undo button)."""
    request.session[UNDO_SESSION_KEY] = {
        "kind": kind,
        "id": str(record_id),
        "label": label,
    }
    # The record's id in the tags ties this message's Undo button to this delete,
    # so an older "Deleted …" message never offers to undo a different record.
    messages.success(request, f"Deleted {label}.", extra_tags=f"undo undo-{record_id}")
