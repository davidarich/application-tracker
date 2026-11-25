"""Template filters for application statuses: {% load tracker_status %}."""

from django import template

from ..status import status_label as _status_label
from ..status import status_slot as _status_slot

register = template.Library()


@register.filter
def status_label(status: str | None) -> str:
    return _status_label(status)


@register.filter
def status_slot(status: str | None) -> int:
    return _status_slot(status)
