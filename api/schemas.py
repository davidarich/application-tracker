"""The JSON shapes the API accepts and returns.

The *In schemas are request bodies for creating records; the *Patch schemas
are the same fields, all optional: only the fields a PATCH sends are changed
(a field sent as null is refused unless null is a valid value, like a salary).
Rules beyond the JSON shape (lengths, URLs, unique names, salary order) are
checked by the web app's own forms, so the API and the site agree.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from ninja import Schema
from pydantic import Field

# Application.Status and Job.WorkplaceType values (tests keep these in step).
type StatusValue = Literal[
    "applied", "responded", "interviewing", "offer", "closed", "ignored"
]
type WorkplaceValue = Literal["", "in_office", "hybrid", "remote"]
# CreationSource values: how a record was created. Read-only: the API sets
# "api" on the records it creates (the MCP server "mcp"), and request bodies
# can't change it.
type CreationSourceValue = Literal["manual", "api", "mcp"]
# A status filter: a status, "none" (not applied yet), "open" (everything but
# closed and ignored) or "all".
type StatusFilter = Literal[
    "all",
    "open",
    "none",
    "applied",
    "responded",
    "interviewing",
    "offer",
    "closed",
    "ignored",
]

MAX_PAGE_SIZE = 100


class ErrorOut(Schema):
    detail: str
    # For 422s: each invalid field's messages, e.g. {"title": ["This field is required."]}.
    errors: dict[str, list[str]] | None = None


# The error responses every endpoint can give, for the OpenAPI docs.
ERRORS: dict[int, type[ErrorOut]] = {
    401: ErrorOut,  # no access token, or a wrong, expired or revoked one
    403: ErrorOut,  # staff only
    404: ErrorOut,
    409: ErrorOut,  # clashed with a record saved at the same moment
    422: ErrorOut,  # invalid fields: see `errors`
}


class Page[T](Schema):
    count: int  # all the matching records, not just this page
    items: list[T]


class PageParams(Schema):
    limit: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE)] = 25
    offset: Annotated[int, Field(ge=0)] = 0


class SearchParams(PageParams):
    q: Annotated[str, Field(max_length=200)] = ""


# --- Skills ------------------------------------------------------------------------


class SkillRef(Schema):
    id: uuid.UUID
    name: str


class SkillOut(SkillRef):
    description: str
    creation_source: CreationSourceValue


class SkillIn(Schema):
    name: str
    description: str = ""


class SkillPatch(Schema):
    name: str = ""
    description: str = ""


# --- Companies ---------------------------------------------------------------------


class CompanyRef(Schema):
    id: uuid.UUID
    name: str


class CompanyOut(CompanyRef):
    website: str
    mission_statement: str
    is_staffing_agency: bool
    job_count: int  # the company's jobs (not deleted)
    date_added: datetime
    creation_source: CreationSourceValue


class CompanyIn(Schema):
    name: str
    website: str = ""
    mission_statement: str = ""
    is_staffing_agency: bool = False


class CompanyPatch(Schema):
    name: str = ""
    website: str = ""
    mission_statement: str = ""
    is_staffing_agency: bool = False


# --- Jobs --------------------------------------------------------------------------

COMPANY_HELP = "The ID of one of your companies. Give this or company_name."
COMPANY_NAME_HELP = (
    "A company name, matched to one of your companies ignoring case; "
    + "a new company is created if none matches. Give this or company."
)
SKILLS_HELP = (
    "Skill IDs or names (names are matched ignoring case). Unknown skills are "
    + "refused: only staff can add skills. On PATCH, replaces the job's skills."
)
STATUS_HELP = (
    "The job's application status. On create, leave it out for a job you "
    + "haven't applied to yet. Every change is recorded in the status history."
)


class JobOut(Schema):
    id: uuid.UUID
    title: str
    company: CompanyRef
    posting_url: str
    location_city: str
    location_state: str
    workplace_type: WorkplaceValue
    salary_min: int | None
    salary_max: int | None
    description: str
    skills: list[SkillRef]
    status: StatusValue | None  # None: not applied yet
    date_added: datetime
    updated_at: datetime  # the latest status change, else when it was added
    creation_source: CreationSourceValue
    # The hiring system the posting link belongs to, e.g. "Greenhouse"; None
    # if there's no link or it isn't recognised.
    hiring_system: str | None


class JobIn(Schema):
    company: uuid.UUID | None = Field(default=None, description=COMPANY_HELP)
    company_name: str | None = Field(default=None, description=COMPANY_NAME_HELP)
    title: str
    posting_url: str = ""
    location_city: str = ""
    location_state: str = ""
    workplace_type: WorkplaceValue = ""
    salary_min: int | None = None
    salary_max: int | None = None
    description: str = ""
    skills: list[str] = Field(default_factory=list, description=SKILLS_HELP)
    status: StatusValue | None = Field(default=None, description=STATUS_HELP)


class JobPatch(Schema):
    company: uuid.UUID | None = Field(default=None, description=COMPANY_HELP)
    company_name: str | None = Field(default=None, description=COMPANY_NAME_HELP)
    title: str = ""
    posting_url: str = ""
    location_city: str = ""
    location_state: str = ""
    workplace_type: WorkplaceValue = ""
    salary_min: int | None = None
    salary_max: int | None = None
    description: str = ""
    skills: list[str] = Field(default_factory=list, description=SKILLS_HELP)
    status: StatusValue | None = Field(default=None, description=STATUS_HELP)


POSTING_URL_HELP = (
    "Only jobs with this posting link. Copies of a link that differ only in "
    + "tracking parameters (utm_source and the like), http or https, www., "
    + "letter case, a trailing slash, the order of query parameters or an "
    + "#anchor match. Leave it out or empty to not filter by link."
)


class JobParams(SearchParams):
    status: StatusFilter = "all"
    company: uuid.UUID | None = None
    # Longer than a saved link (200 characters) may be, since the tracking
    # parameters are removed before matching.
    posting_url: Annotated[
        str, Field(max_length=2000, description=POSTING_URL_HELP)
    ] = ""
