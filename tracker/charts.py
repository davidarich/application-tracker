"""Data and geometry for the dashboard's "Applications by status" chart."""

import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from accounts.models import User

from .models import Application, ApplicationStatusChange
from .ownership import status_changes_for
from .status import STATUS_ORDER, status_slot

DEFAULT_DAYS = 14

# The plot is drawn in an SVG with this viewBox and preserveAspectRatio="none",
# so it stretches to its container; strokes use non-scaling-stroke.
PLOT_WIDTH = 1000
PLOT_HEIGHT = 300

# A band gets a direct label at the right edge only when it is at least this
# share of the plot height, so labels never collide; the legend, tooltip and
# table carry the rest.
MIN_LABELLED_BAND = 0.08

# The statuses the chart shows: the open pipeline, without closed or ignored jobs.
CHART_STATUSES: list[Application.Status] = [
    status
    for status in STATUS_ORDER
    if status not in (Application.Status.CLOSED, Application.Status.IGNORED)
]


@dataclass(frozen=True)
class StatusCounts:
    """How many applications were in each status at the end of each day."""

    days: list[date]
    counts: dict[Application.Status, list[int]]

    @property
    def totals(self) -> list[int]:
        return [sum(day) for day in zip(*self.counts.values(), strict=True)]


def status_counts(
    user: User, days: int = DEFAULT_DAYS, today: date | None = None
) -> StatusCounts:
    """Count `user`'s applications by status at the end of each of the last `days` days.

    The last day is `today` (the current local date by default). An application
    is counted on a day from the day it was created, in the status it had at the
    end of that day, according to its ApplicationStatusChange history.
    """
    today = today or timezone.localdate()
    day_list = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    tz = timezone.get_current_timezone()
    day_ends = [
        datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
        for day in day_list
    ]

    changes = (
        status_changes_for(user)
        .filter(changed_at__lt=day_ends[-1])
        .select_related("application")
        .only("status", "changed_at", "application__id")
        .order_by("application", "changed_at")
    )
    histories: dict[uuid.UUID, list[ApplicationStatusChange]] = {}
    for change in changes:
        histories.setdefault(change.application.id, []).append(change)

    counts = {status: [0] * days for status in Application.Status}
    for history in histories.values():
        position = 0
        current: Application.Status | None = None
        for index, day_end in enumerate(day_ends):
            while position < len(history) and history[position].changed_at < day_end:
                current = Application.Status(history[position].status)
                position += 1
            if current is not None:
                counts[current][index] += 1

    return StatusCounts(days=day_list, counts=counts)


@dataclass(frozen=True)
class Tick:
    value: int
    top: float  # percent from the top of the plot


@dataclass(frozen=True)
class DayLabel:
    text: str
    left: float  # percent from the left of the plot
    align: str  # "start", "center" or "end", so the edge labels stay inside
    # Labelled days count back from today: every 2nd on wider screens, every
    # 3rd on small ones, so labels never collide.
    on_desktop: bool
    on_mobile: bool
    is_today: bool


@dataclass(frozen=True)
class Band:
    status: Application.Status
    label: str
    slot: int  # categorical colour slot, fixed per status
    counts: list[int]
    area_path: str
    line_path: str
    latest: int
    label_top: float | None  # percent from the top, or None when too thin to label


@dataclass(frozen=True)
class DayRow:
    day: date
    counts: list[int]
    total: int


@dataclass(frozen=True)
class StatusChart:
    days: list[date]
    bands: list[Band]
    ticks: list[Tick]
    day_labels: list[DayLabel]
    rows: list[DayRow]
    top: int
    is_empty: bool
    width: int = PLOT_WIDTH
    height: int = PLOT_HEIGHT

    def to_json(self) -> dict[str, object]:
        """The data the hover layer needs (passed to the page with json_script)."""
        return {
            "days": [f"{day:%a %b} {day.day}" for day in self.days],
            "top": self.top,
            "series": [
                {"label": band.label, "slot": band.slot, "counts": band.counts}
                for band in self.bands
            ],
        }


def nice_scale(maximum: int, intervals: int = 4) -> tuple[int, int]:
    """Return (top, step): a clean axis top and integer tick step covering `maximum`."""
    if maximum <= 0:
        return intervals, 1
    raw_step = maximum / intervals
    magnitude = 10.0 ** math.floor(math.log10(raw_step))
    step = next(m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= raw_step)
    step = max(1, math.ceil(step))
    return math.ceil(maximum / step) * step, step


def build_status_chart(data: StatusCounts) -> StatusChart:
    """Lay out `data` as a stacked area chart of the CHART_STATUSES, bottom band first.

    Closed and ignored jobs aren't charted, and don't count towards the axis
    scale, the table totals or whether the chart is empty.
    """
    n = len(data.days)
    totals = [
        sum(data.counts[status][i] for status in CHART_STATUSES) for i in range(n)
    ]
    top, step = nice_scale(max(totals, default=0))

    def x(index: int) -> float:
        return index / (n - 1) * PLOT_WIDTH if n > 1 else PLOT_WIDTH / 2

    def y(value: int) -> float:
        return PLOT_HEIGHT - value / top * PLOT_HEIGHT

    def points(values: list[int]) -> list[str]:
        return [f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values)]

    bands: list[Band] = []
    lower = [0] * n
    for status in CHART_STATUSES:
        counts = data.counts[status]
        upper = [base + count for base, count in zip(lower, counts, strict=True)]
        upper_points = points(upper)
        lower_points = points(lower)
        latest = counts[-1]
        label_top = None
        if latest / top >= MIN_LABELLED_BAND:
            label_top = (1 - (lower[-1] + upper[-1]) / 2 / top) * 100
        bands.append(
            Band(
                status=status,
                label=str(status.label),
                slot=status_slot(status),
                counts=counts,
                area_path="M" + " L".join(upper_points + lower_points[::-1]) + " Z",
                line_path="M" + " L".join(upper_points),
                latest=latest,
                label_top=label_top,
            )
        )
        lower = upper

    ticks = [Tick(value=v, top=(1 - v / top) * 100) for v in range(0, top + 1, step)]

    today = data.days[-1]
    day_labels = [
        DayLabel(
            text=f"{day:%b} {day.day}",
            left=x(i) / PLOT_WIDTH * 100,
            align="start" if i == 0 else "end" if i == n - 1 else "center",
            on_desktop=(n - 1 - i) % 2 == 0,
            on_mobile=(n - 1 - i) % 3 == 0,
            is_today=day == today,
        )
        for i, day in enumerate(data.days)
    ]

    rows = [
        DayRow(day=day, counts=[band.counts[i] for band in bands], total=totals[i])
        for i, day in enumerate(data.days)
    ]

    return StatusChart(
        days=data.days,
        bands=bands,
        ticks=ticks,
        day_labels=day_labels,
        rows=rows,
        top=top,
        is_empty=max(totals, default=0) == 0,
    )
