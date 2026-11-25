"""The MCP server's tools, and the Starlette app that serves them.

Each tool runs its work in Django's thread for synchronous code (the ORM
isn't async), as the user of the request's access token, by calling the
same function the JSON API's endpoint calls (api/services/). Expected
failures come back as tool errors (is_error results) with the API's
wording, so the agent can fix its request: invalid fields, not found,
staff only, or a clash with a record saved at the same moment.
"""

import inspect
import uuid
from collections.abc import Callable
from typing import Annotated, cast, override
from urllib.parse import urlsplit

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import IntegrityError
from django.http import Http404
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import Tool, ToolAnnotations
from ninja.errors import HttpError
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from accounts.models import User
from api.errors import INVALID_FIELDS, FieldErrors
from api.schemas import (
    MAX_PAGE_SIZE,
    POSTING_URL_HELP,
    CompanyIn,
    CompanyOut,
    CompanyPatch,
    JobIn,
    JobOut,
    JobParams,
    JobPatch,
    Page,
    SearchParams,
    SkillIn,
    SkillOut,
    SkillPatch,
    StatusFilter,
    StatusValue,
)
from api.services import companies, jobs, skills
from tracker.models import CreationSource

from .auth import (
    GrantTokenVerifier,
    request_subject,
    tidy_connections,
    user_for_subject,
)

SOURCE = CreationSource.MCP
CLASH = "That clashes with a record saved at the same time. Try again."
NO_USER = "Your access has ended. Connect the app to Job Tracker again."
# Tools only staff see (and only staff can use).
STAFF_TOOLS = frozenset({"create_skill", "update_skill"})

INSTRUCTIONS = """\
Job Tracker keeps track of a person's job search: the jobs they're
interested in or applied to (with an application status), the companies
behind them, and a shared list of skills that jobs ask for.

- Before adding a job from a posting link, call list_jobs with posting_url
  to check it isn't saved already.
- A job's company can be given by name (company_name): it's matched to one
  of the user's companies ignoring case, or created.
- Skills must already exist (list_skills); they can be given by name.
- Status history is kept: set_job_status records each change.
- Nothing can be deleted through this server.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
CREATES = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, open_world_hint=False
)
CHANGES = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

type Limit = Annotated[
    int, Field(ge=1, le=MAX_PAGE_SIZE, description="Results per page.")
]
type Offset = Annotated[int, Field(ge=0, description="Results to skip, for paging.")]
type Query = Annotated[str, Field(max_length=200, description="Text to search for.")]


def field_errors_text(errors: dict[str, list[str]]) -> str:
    lines = [INVALID_FIELDS]
    lines.extend(
        f"- {field}: {' '.join(messages)}" for field, messages in errors.items()
    )
    return "\n".join(lines)


def run_as_user[T](subject: str | None, work: Callable[[User], T]) -> T:
    """Do `work` as the user with ID `subject`, turning expected failures
    into tool errors (the SDK reports anything else as a crash, without
    details)."""
    tidy_connections()
    try:
        user = user_for_subject(subject)
        if user is None:
            raise ToolError(NO_USER)
        return work(user)
    except FieldErrors as error:
        raise ToolError(field_errors_text(error.errors)) from error
    except Http404 as error:
        raise ToolError(str(error) or "Not found.") from error
    except HttpError as error:
        raise ToolError(error.message) from error
    except IntegrityError as error:
        raise ToolError(CLASH) from error
    finally:
        tidy_connections()


async def as_user[T](work: Callable[[User], T]) -> T:
    """run_as_user() for the current request's user, in Django's thread for
    synchronous code."""
    subject = request_subject()  # read here: it's in the request's context
    return await sync_to_async(run_as_user, thread_sensitive=True)(subject, work)


class TrackerServer(MCPServer[None]):
    """An MCPServer that lists the staff-only tools only to staff."""

    @override
    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        if await as_user(lambda user: user.is_staff):
            return tools
        return [tool for tool in tools if tool.name not in STAFF_TOOLS]


def add_tools(server: MCPServer[None]) -> None:
    def tool[F: Callable[..., object]](
        annotations: ToolAnnotations, title: str
    ) -> Callable[[F], F]:
        def register(fn: F) -> F:
            _ = server.tool(
                title=title,
                description=inspect.cleandoc(fn.__doc__ or ""),
                annotations=annotations,
            )(fn)
            return fn

        return register

    # --- Jobs ----------------------------------------------------------------------

    @tool(READ_ONLY, "List jobs")
    async def list_jobs(
        q: Annotated[
            str,
            Field(max_length=200, description="Searches job titles and company names."),
        ] = "",
        status: Annotated[
            StatusFilter,
            Field(
                description=(
                    'A status, "none" (not applied yet), "open" (everything but '
                    + 'closed and ignored) or "all".'
                )
            ),
        ] = "all",
        company: Annotated[
            uuid.UUID | None, Field(description="Only jobs at this company (its ID).")
        ] = None,
        posting_url: Annotated[
            str, Field(max_length=2000, description=POSTING_URL_HELP)
        ] = "",
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Page[JobOut]:
        """The user's jobs, most recently updated first, with their company,
        skills and application status. Filter by text, status, company or
        posting link (to check whether a posting is already saved)."""
        params = JobParams(
            q=q,
            status=status,
            company=company,
            posting_url=posting_url,
            limit=limit,
            offset=offset,
        )
        return await as_user(lambda user: jobs.list_jobs(user, params))

    @tool(READ_ONLY, "Get a job")
    async def get_job(job_id: uuid.UUID) -> JobOut:
        """One of the user's jobs, by ID."""
        return await as_user(lambda user: jobs.job_detail(user, job_id))

    @tool(CREATES, "Add a job")
    async def create_job(job: JobIn) -> JobOut:
        """Add a job. Give its company as `company` (one of the user's company
        IDs) or `company_name` (matched ignoring case, or created). Skills are
        IDs or names of existing skills. Leave `status` out for a job the user
        hasn't applied to. Check list_jobs with posting_url first, to avoid
        saving a posting twice."""
        return await as_user(lambda user: jobs.create_job(user, job, SOURCE))

    @tool(CHANGES, "Change a job")
    async def update_job(job_id: uuid.UUID, changes: JobPatch) -> JobOut:
        """Change one of the user's jobs: only the fields given in `changes`
        are changed. `skills` replaces the job's skills; a new `status` is
        added to its status history (a status can't be removed)."""
        return await as_user(
            lambda user: jobs.update_job(user, job_id, changes, SOURCE)
        )

    @tool(CHANGES, "Set a job's status")
    async def set_job_status(job_id: uuid.UUID, status: StatusValue) -> JobOut:
        """Set the application status of one of the user's jobs (e.g. after
        applying, or when they hear back). Each change is recorded in the
        job's status history."""
        changes = JobPatch(status=status)
        return await as_user(
            lambda user: jobs.update_job(user, job_id, changes, SOURCE)
        )

    # --- Companies -----------------------------------------------------------------

    @tool(READ_ONLY, "List companies")
    async def list_companies(
        q: Annotated[
            str, Field(max_length=200, description="Searches company names.")
        ] = "",
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Page[CompanyOut]:
        """The user's companies, by name, with how many jobs each has."""
        params = SearchParams(q=q, limit=limit, offset=offset)
        return await as_user(lambda user: companies.list_companies(user, params))

    @tool(READ_ONLY, "Get a company")
    async def get_company(company_id: uuid.UUID) -> CompanyOut:
        """One of the user's companies, by ID."""
        return await as_user(lambda user: companies.company_detail(user, company_id))

    @tool(CREATES, "Add a company")
    async def create_company(company: CompanyIn) -> CompanyOut:
        """Add a company. The user's company names are unique, ignoring case."""
        return await as_user(
            lambda user: companies.create_company(user, company, SOURCE)
        )

    @tool(CHANGES, "Change a company")
    async def update_company(
        company_id: uuid.UUID, changes: CompanyPatch
    ) -> CompanyOut:
        """Change one of the user's companies: only the fields given in
        `changes` are changed."""
        return await as_user(
            lambda user: companies.update_company(user, company_id, changes)
        )

    # --- Skills --------------------------------------------------------------------

    @tool(READ_ONLY, "List skills")
    async def list_skills(
        q: Annotated[
            str,
            Field(max_length=200, description="Searches skill names and descriptions."),
        ] = "",
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Page[SkillOut]:
        """The shared list of skills, by name. Jobs can only use these."""
        params = SearchParams(q=q, limit=limit, offset=offset)
        return await as_user(lambda _user: skills.list_skills(params))

    @tool(READ_ONLY, "Get a skill")
    async def get_skill(skill_id: uuid.UUID) -> SkillOut:
        """A skill, by ID."""
        return await as_user(lambda _user: skills.skill_detail(skill_id))

    @tool(CREATES, "Add a skill")
    async def create_skill(skill: SkillIn) -> SkillOut:
        """Add a skill to the shared list (staff only). Names are unique,
        ignoring case."""
        return await as_user(lambda user: skills.create_skill(user, skill, SOURCE))

    @tool(CHANGES, "Change a skill")
    async def update_skill(skill_id: uuid.UUID, changes: SkillPatch) -> SkillOut:
        """Change a skill (staff only): only the fields given in `changes`
        are changed."""
        return await as_user(lambda user: skills.update_skill(user, skill_id, changes))


def build_server() -> TrackerServer:
    resource = cast(str, settings.MCP_RESOURCE_URL)
    issuer = cast(str, settings.OAUTH_ISSUER)
    server = TrackerServer(
        name="job-tracker",
        title="Job Tracker",
        instructions=INSTRUCTIONS,
        # The SDK configures the root logger at this level (uvicorn logs
        # requests itself).
        log_level="WARNING",
        token_verifier=GrantTokenVerifier(),
        # From strings, which AuthSettings keeps exactly as given: an issuer
        # must match character for character (RFC 8414), and AnyHttpUrl()
        # would add a trailing slash.
        auth=AuthSettings.model_validate(
            {
                "issuer_url": issuer,
                "resource_server_url": resource,
                # GrantTokenVerifier accepts only MCP grants' tokens itself.
                "validate_token_resource": False,
            }
        ),
    )
    add_tools(server)

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    # Clients that don't use the path-suffixed URL (RFC 9728 section 3.1)
    # look for the protected resource metadata at the root.
    @server.custom_route(
        "/.well-known/oauth-protected-resource",
        methods=["GET"],
        include_in_schema=False,
    )
    async def resource_metadata(_request: Request) -> Response:
        return JSONResponse(
            {
                "resource": resource,
                "authorization_servers": [issuer],
                "bearer_methods_supported": ["header"],
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    return server


def allowed_hosts() -> list[str]:
    """Host headers the MCP server answers: the host of its public URL and
    ALLOWED_HOSTS (with any port), plus localhost while DEBUG is on."""
    hosts = {urlsplit(cast(str, settings.MCP_RESOURCE_URL)).netloc}
    names = [
        host
        for host in cast(list[str], settings.ALLOWED_HOSTS)
        if not host.startswith((".", "*"))  # wildcards aren't supported here
    ]
    if cast(bool, settings.DEBUG):
        names += ["localhost", "127.0.0.1", "[::1]"]
    for name in names:
        hosts.update({name, f"{name}:*"})
    return sorted(hosts)


def build_app() -> ASGIApp:
    """The ASGI app: Streamable HTTP at MCP_RESOURCE_URL's path, stateless
    (no sessions, so any worker can answer any request) with JSON responses.
    Requests with a Host or Origin header that isn't allowed are refused
    (guarding against DNS rebinding)."""
    server = build_server()
    path = urlsplit(cast(str, settings.MCP_RESOURCE_URL)).path or "/mcp"
    origins = cast(list[str], settings.MCP_ALLOWED_ORIGINS)
    app: Starlette = server.streamable_http_app(
        streamable_http_path=path,
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts(),
            allowed_origins=origins,
        ),
    )
    if not origins:
        return app
    # Browser-based MCP clients on these origins can call the server.
    return CORSMiddleware(
        app,
        allow_origins=origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Mcp-Protocol-Version",
            "Mcp-Session-Id",
            "Last-Event-ID",
        ],
        expose_headers=["WWW-Authenticate", "Mcp-Session-Id"],
    )
