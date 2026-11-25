"""Paging list endpoints with limit and offset."""

from collections.abc import Callable

from django.db.models import Model, QuerySet

from .schemas import Page, PageParams


def page_of[M: Model, T](
    records: QuerySet[M], params: PageParams, out: Callable[[M], T]
) -> Page[T]:
    """One page of `records` (which must be ordered), each turned into `out`."""
    window = records[params.offset : params.offset + params.limit]
    return Page[T](count=records.count(), items=[out(record) for record in window])
