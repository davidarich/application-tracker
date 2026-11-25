"""Presentation details for application statuses, shared by the chart and tables."""

from .models import Application

Status = Application.Status

# Pipeline order. Also the chart's stacking order and each status's colour slot.
STATUS_ORDER: list[Application.Status] = list(Status)

NOT_APPLIED_LABEL = "Not applied"


def status_slot(status: str | None) -> int:
    """The status's categorical colour slot (1-based; --chart-N), or 0 for none."""
    if status is None or status not in Status.values:
        return 0
    return STATUS_ORDER.index(Status(status)) + 1


def status_label(status: str | None) -> str:
    """The status's display label, or "Not applied" for a job with no application."""
    if status is None or status not in Status.values:
        return NOT_APPLIED_LABEL
    return str(Status(status).label)
