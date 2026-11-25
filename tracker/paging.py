"""Paging for lists (the dashboard's jobs, the companies page).

The page and page size are GET parameters, so a paged view survives a reload
and can be bookmarked:

    page      the page number (bad or out-of-range numbers fall back safely)
    per_page  items per page, one of PAGE_SIZES (default DEFAULT_PAGE_SIZE)

Templates show the footer with partials/pagination.html and paging_context().
"""

from django.core.paginator import Page
from django.http import QueryDict

PAGE_SIZES: tuple[int, ...] = (25, 50, 100, 250)
DEFAULT_PAGE_SIZE = 25


def parse_per_page(params: QueryDict) -> int:
    """The per_page parameter if it's one of PAGE_SIZES, else the default."""
    raw = params.get("per_page", "")
    return int(raw) if raw in {str(size) for size in PAGE_SIZES} else DEFAULT_PAGE_SIZE


def page_numbers(current: int, total: int, around: int = 1) -> list[int | None]:
    """Page links to show: the first and last pages, `around` pages either side
    of `current`, and None where a run of pages is elided ("...").

    >>> page_numbers(6, 12)
    [1, None, 5, 6, 7, None, 12]
    """
    shown = {1, total, *range(current - around, current + around + 1)}
    numbers: list[int | None] = []
    previous = 0
    for number in sorted(n for n in shown if 1 <= n <= total):
        if number - previous == 2:
            numbers.append(number - 1)  # a gap of one page: show it, not "..."
        elif number - previous > 2:
            numbers.append(None)
        numbers.append(number)
        previous = number
    return numbers


def paging_context(page: Page, per_page: int, anchor: str) -> dict[str, object]:
    """What partials/pagination.html needs. `anchor` is the id of the section
    the page links return to (e.g. "jobs"), so the browser doesn't jump to the top."""
    return {
        "page": page,
        "page_numbers": page_numbers(page.number, page.paginator.num_pages),
        "page_sizes": PAGE_SIZES,
        "per_page": per_page,
        "paging_anchor": anchor,
    }
