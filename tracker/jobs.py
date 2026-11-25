"""Filtering and sorting for the dashboard's job list.

Filters arrive as GET parameters, so a filtered, sorted view survives a reload
and can be bookmarked:

    q        text matched against job title and company name
    status   "open" (default: everything except closed), "all", "none" (no
             application yet) or an Application.Status value
    company  a company id
    sort     a column name, "-" prefixed for descending (default "-updated")
    per_page jobs per page (see tracker/paging.py)
    page     the page number (read by the view's paginator, not JobFilters)
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Self, cast

from django.db.models import (
    Case,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.expressions import OrderBy
from django.db.models.functions import Coalesce
from django.http import QueryDict

from accounts.models import User

from .models import Application, ApplicationStatusChange, Company, Job
from .ownership import applications_for, companies_for, jobs_for
from .paging import DEFAULT_PAGE_SIZE, parse_per_page
from .status import NOT_APPLIED_LABEL, STATUS_ORDER, status_label, status_slot

Status = Application.Status

STATUS_OPEN = "open"
# Hidden by the default "open" filter: jobs that are over, or not being pursued.
FINISHED_STATUSES = (Status.CLOSED, Status.IGNORED)
STATUS_ALL = "all"
STATUS_NONE = "none"

STATUS_FILTER_OPTIONS: list[tuple[str, str]] = [
    (STATUS_OPEN, "Open (hide closed & ignored)"),
    (STATUS_ALL, "All statuses"),
    (STATUS_NONE, NOT_APPLIED_LABEL),
    *((str(status.value), str(status.label)) for status in STATUS_ORDER),
]

# Sortable columns: name -> (heading, ORM field, direction of the first click).
SORT_COLUMNS: dict[str, tuple[str, str, str]] = {
    "title": ("Job title", "title", "asc"),
    "company": ("Company", "company__name", "asc"),
    "status": ("Status", "status_rank", "asc"),
    "updated": ("Updated", "last_updated", "desc"),
}
DEFAULT_SORT = "-updated"

# Secondary orderings, in priority order: most recently updated, then status in
# pipeline order (not applied first, closed last), then title. With the default
# sort, jobs updated at the same time are therefore ordered by status.
TIE_BREAKERS: list[tuple[str, OrderBy]] = [
    ("last_updated", F("last_updated").desc()),
    ("status_rank", F("status_rank").asc()),
    ("title", F("title").asc()),
]


@dataclass(frozen=True)
class JobFilters:
    query: str = ""
    status: str = STATUS_OPEN
    company: uuid.UUID | None = None
    sort: str = DEFAULT_SORT
    per_page: int = DEFAULT_PAGE_SIZE

    @classmethod
    def from_query(cls, params: QueryDict) -> Self:
        """Read filters from GET parameters, falling back to defaults for bad values."""
        status = params.get("status", STATUS_OPEN)
        if status not in dict(STATUS_FILTER_OPTIONS):
            status = STATUS_OPEN

        company: uuid.UUID | None
        try:
            company = uuid.UUID(params.get("company", ""))
        except ValueError:
            company = None

        sort = params.get("sort", DEFAULT_SORT)
        if sort.removeprefix("-") not in SORT_COLUMNS:
            sort = DEFAULT_SORT

        return cls(
            query=params.get("q", "").strip()[:200],
            status=status,
            company=company,
            sort=sort,
            per_page=parse_per_page(params),
        )

    @property
    def is_filtered(self) -> bool:
        """Whether any filter differs from the default (sorting and paging aside)."""
        return (
            replace(self, sort=DEFAULT_SORT, per_page=DEFAULT_PAGE_SIZE) != JobFilters()
        )


def job_list(user: User, filters: JobFilters) -> QuerySet[Job]:
    """`user`'s jobs matching `filters`, sorted, each annotated with:

    latest_status  the status of its most recent application, or None
    last_updated   when that application last changed, else when the job was added
    status_rank    pipeline position for sorting (0 = not applied yet)
    """
    latest_application = Application.objects.filter(job=OuterRef("pk")).order_by(
        "-created_at"
    )
    jobs = (
        jobs_for(user)
        .select_related("company")
        .annotate(
            latest_status=Subquery(latest_application.values("status")[:1]),
            last_updated=Coalesce(
                Subquery(latest_application.values("updated_at")[:1]), F("date_added")
            ),
        )
        .annotate(
            status_rank=Case(
                *(
                    When(latest_status=status.value, then=Value(rank))
                    for rank, status in enumerate(STATUS_ORDER, start=1)
                ),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
    )

    if filters.query:
        jobs = jobs.filter(
            Q(title__icontains=filters.query)
            | Q(company__name__icontains=filters.query)
        )

    if filters.status == STATUS_OPEN:
        # Spelled out rather than excluding "closed": NOT (NULL = 'closed') is
        # NULL in SQL, which would also drop jobs with no application.
        open_statuses = [s.value for s in STATUS_ORDER if s not in FINISHED_STATUSES]
        jobs = jobs.filter(
            Q(latest_status__isnull=True) | Q(latest_status__in=open_statuses)
        )
    elif filters.status == STATUS_NONE:
        jobs = jobs.filter(latest_status__isnull=True)
    elif filters.status != STATUS_ALL:
        jobs = jobs.filter(latest_status=filters.status)

    if filters.company is not None:
        jobs = jobs.filter(company_id=filters.company)

    column = filters.sort.removeprefix("-")
    field = SORT_COLUMNS[column][1]
    primary = F(field).desc() if filters.sort.startswith("-") else F(field).asc()
    # Ties fall back to the TIE_BREAKERS (skipping the column already sorted
    # on), then the job id, so the order is stable across pages.
    tie_breakers = [order for name, order in TIE_BREAKERS if name != field]
    return jobs.order_by(primary, *tie_breakers, F("id").asc())


@dataclass(frozen=True)
class SortColumn:
    name: str
    heading: str
    next_sort: str  # the sort a click on the heading applies
    direction: str | None  # "ascending"/"descending" when this is the active sort


def sort_columns(filters: JobFilters) -> list[SortColumn]:
    """Header state for each sortable column: clicking the active one flips it."""
    active = filters.sort.removeprefix("-")
    descending = filters.sort.startswith("-")
    columns: list[SortColumn] = []
    for name, (heading, _field, first) in SORT_COLUMNS.items():
        if name == active:
            next_sort = name if descending else f"-{name}"
            direction = "descending" if descending else "ascending"
        else:
            next_sort = f"-{name}" if first == "desc" else name
            direction = None
        columns.append(SortColumn(name, heading, next_sort, direction))
    return columns


def company_options(user: User) -> QuerySet[Company]:
    return companies_for(user).only("id", "name").order_by("name")


# --- Kanban board -----------------------------------------------------------

# The board's columns: "not applied" (None) and the open statuses. Closed and
# ignored jobs aren't on the board.
KANBAN_STATUSES: list[str | None] = [
    None,
    *(str(status.value) for status in STATUS_ORDER if status not in FINISHED_STATUSES),
]
KANBAN_COLUMN_LIMIT = 100  # cards shown per column


def latest_status_of(job: Job) -> str | None:
    """The latest_status that job_list() annotates (None: not applied yet)."""
    return cast(str | None, vars(job).get("latest_status"))


@dataclass(frozen=True)
class KanbanColumn:
    status: str | None
    label: str
    slot: int  # colour slot (--chart-N); 0 for not applied
    jobs: list[Job]
    count: int  # all the column's jobs, even past KANBAN_COLUMN_LIMIT


def kanban_columns(user: User, filters: JobFilters) -> list[KanbanColumn]:
    """`user`'s open jobs, grouped by status, most recently updated first.

    The search and company filters apply; the status filter and sorting don't
    (the columns are the statuses).
    """
    board = replace(filters, status=STATUS_OPEN, sort=DEFAULT_SORT)
    grouped: dict[str | None, list[Job]] = {status: [] for status in KANBAN_STATUSES}
    for job in job_list(user, board):
        grouped.setdefault(latest_status_of(job), []).append(job)
    return [
        KanbanColumn(
            status=status,
            label=status_label(status),
            slot=status_slot(status),
            jobs=grouped[status][:KANBAN_COLUMN_LIMIT],
            count=len(grouped[status]),
        )
        for status in KANBAN_STATUSES
    ]


@dataclass(frozen=True)
class StatusMove:
    """What set_job_status() changed, so it can be undone exactly."""

    application_id: uuid.UUID
    status: str  # the status the job was moved to
    created: bool  # the move created the job's first application
    previous_status: str | None
    previous_updated_at: datetime | None
    change_id: uuid.UUID | None  # the status history entry the move recorded


def set_job_status(job: Job, status: str) -> StatusMove | None:
    """Give `job` a new status; return what changed (None if nothing did).

    A job not applied for yet gets its first application; otherwise its
    latest application (the one the job list shows) is updated. Either way
    Application.save() records the change in the status history.
    """
    latest = Application.objects.filter(job=job).order_by("-created_at").first()
    if latest is None:
        application = Application.objects.create(job=job, status=status)
        return StatusMove(application.id, status, True, None, None, None)
    if latest.status == status:
        return None
    previous_status, previous_updated_at = latest.status, latest.updated_at
    latest.status = status
    latest.save()
    change = (
        ApplicationStatusChange.objects.filter(application=latest)
        .order_by("-changed_at")
        .first()
    )
    return StatusMove(
        latest.id,
        status,
        False,
        previous_status,
        previous_updated_at,
        change.id if change else None,
    )


def undo_status_move(user: User, move: StatusMove) -> str | None:
    """Put a job back as it was before `move`; return why not, if it can't be.

    A move that created the job's first application is undone by deleting
    that application (the job is "not applied" again). Otherwise the status
    and last-updated time are restored and the move's history entry removed,
    so the history reads as if the move never happened.
    """
    application = applications_for(user).filter(id=move.application_id).first()
    if application is None:
        return "the job no longer exists."
    newer = Application.objects.filter(
        job=application.job, created_at__gt=application.created_at
    )
    if application.status != move.status or newer.exists():
        return "its status has changed since."
    if move.created:
        _ = application.delete()
        return None
    if move.change_id is not None:
        _ = ApplicationStatusChange.objects.filter(
            id=move.change_id, application=application
        ).delete()
    _ = Application.objects.filter(id=application.id).update(
        status=move.previous_status, updated_at=move.previous_updated_at
    )
    return None
