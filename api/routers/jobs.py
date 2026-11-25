"""The user's jobs: list, read, create and change, including their status."""

import uuid
from datetime import datetime
from typing import cast

from django.db import transaction
from django.db.models import Prefetch, QuerySet
from django.db.models.functions import Lower
from django.http import Http404, HttpRequest
from ninja import Query, Router

from accounts.models import User
from tracker.forms import CompanyForm, make_job_form, save_company_form
from tracker.jobs import (
    STATUS_ALL,
    JobFilters,
    job_list,
    latest_status_of,
    set_job_status,
)
from tracker.models import Company, CreationSource, Job
from tracker.ownership import active_skills, companies_for
from tracker.posting_urls import posting_url_key

from ..auth import api_user
from ..errors import FieldErrors, form_data, form_errors
from ..paging import page_of
from ..schemas import (
    ERRORS,
    CompanyRef,
    CreationSourceValue,
    JobIn,
    JobOut,
    JobParams,
    JobPatch,
    Page,
    SkillRef,
    StatusValue,
    WorkplaceValue,
)

router = Router(tags=["Jobs"])

type FormValues = dict[str, str | list[str]]

NO_COMPANY = "Give company (one of your company IDs) or company_name."


def with_skills(jobs: QuerySet[Job]) -> QuerySet[Job]:
    return jobs.select_related("company").prefetch_related(
        Prefetch("skills", queryset=active_skills().order_by(Lower("name")))
    )


def job_out(job: Job) -> JobOut:
    """A job from job_list(), which annotates its status and last update."""
    return JobOut(
        id=job.id,
        title=job.title,
        company=CompanyRef(id=job.company.id, name=job.company.name),
        posting_url=job.posting_url,
        location_city=job.location_city,
        location_state=job.location_state,
        workplace_type=cast(WorkplaceValue, job.workplace_type),
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        description=job.description,
        skills=[SkillRef(id=skill.id, name=skill.name) for skill in job.skills.all()],
        status=cast(StatusValue | None, latest_status_of(job)),
        date_added=job.date_added,
        updated_at=cast(datetime, vars(job)["last_updated"]),
        creation_source=cast(CreationSourceValue, job.creation_source),
        hiring_system=system.name if (system := job.hiring_system) else None,
    )


def get_job(user: User, job_id: uuid.UUID) -> Job:
    """One of `user`'s jobs (anyone else's is a 404, as if it didn't exist)."""
    jobs = with_skills(job_list(user, JobFilters(status=STATUS_ALL)))
    job = jobs.filter(id=job_id).first()
    if job is None:
        raise Http404("No job with this ID.")
    return job


def resolve_skills(entries: list[str]) -> list[str]:
    """The IDs of the skills named by ID or name (ignoring case), in order,
    without repeats; unknown skills are refused, since only staff add skills."""
    found: list[str] = []
    unknown: list[str] = []
    skills = active_skills()
    for entry in entries:
        text = entry.strip()
        try:
            skill = skills.filter(id=uuid.UUID(text)).first()
        except ValueError:
            skill = None
        skill = skill or skills.filter(name__iexact=text).first()
        if skill is None:
            unknown.append(text)
        elif str(skill.id) not in found:
            found.append(str(skill.id))
    if unknown:
        raise FieldErrors(
            {
                "skills": [
                    "Unknown skills: "
                    + ", ".join(unknown)
                    + ". Only staff can add skills."
                ]
            }
        )
    return found


def resolve_company(
    user: User, company_id: uuid.UUID | None, company_name: str | None
) -> Company:
    """The company a request names: one of `user`'s companies by ID, or by
    name (ignoring case), creating it if they have none by that name."""
    if company_id is not None and company_name is not None:
        raise FieldErrors({"company": ["Give company or company_name, not both."]})
    if company_id is not None:
        company = companies_for(user).filter(id=company_id).first()
        if company is None:
            raise FieldErrors({"company": ["You have no company with this ID."]})
        return company
    name = (company_name or "").strip()
    if not name:
        raise FieldErrors({"company": [NO_COMPANY]})
    existing = companies_for(user).filter(name__iexact=name).first()
    if existing is not None:
        return existing
    company = Company(user_owner=user, creation_source=CreationSource.API)
    form = CompanyForm(form_data({"name": name}), instance=company)
    if not save_company_form(form, user):
        raise FieldErrors(form_errors(form, {"name": "company_name"}))
    return company


def job_values(payload: JobIn | JobPatch) -> FormValues:
    """The job form values a request sends (for a PATCH, only the fields it
    sent). The company, skills and status are handled separately."""
    values: FormValues = {
        "title": payload.title,
        "posting_url": payload.posting_url,
        "location_city": payload.location_city,
        "location_state": payload.location_state,
        "workplace_type": payload.workplace_type,
        "salary_min": "" if payload.salary_min is None else str(payload.salary_min),
        "salary_max": "" if payload.salary_max is None else str(payload.salary_max),
        "description": payload.description,
    }
    if isinstance(payload, JobIn):
        return values
    return {k: v for k, v in values.items() if k in payload.model_fields_set}


def current_values(job: Job) -> FormValues:
    """`job` as job form values, the starting point for a PATCH."""
    return {
        "company": str(job.company.id),
        "title": job.title,
        "posting_url": job.posting_url,
        "location_city": job.location_city,
        "location_state": job.location_state,
        "workplace_type": job.workplace_type,
        "salary_min": "" if job.salary_min is None else str(job.salary_min),
        "salary_max": "" if job.salary_max is None else str(job.salary_max),
        "description": job.description,
        "skills": [str(skill.id) for skill in job.skills.all()],
    }


def with_posting_url(jobs: QuerySet[Job], url: str) -> QuerySet[Job]:
    """The `jobs` whose posting link is the same posting as `url`, comparing
    posting_url_key()s, so tracking parameters, a trailing slash, www. and
    the like don't matter."""
    key = posting_url_key(url)
    if not key:
        return jobs.none()
    # Only links on the same site can match; narrow to those in the database.
    host = key.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    candidates = (
        jobs.filter(posting_url__icontains=host)
        .select_related(None)  # job_list() joins the company; not needed here
        .only("id", "posting_url")
    )
    matches = [job.id for job in candidates if posting_url_key(job.posting_url) == key]
    return jobs.filter(id__in=matches)


def save_job(user: User, data: FormValues, job: Job | None = None) -> Job:
    """Validate and save a job with the web app's form."""
    form = make_job_form(form_data(data), user, job)
    if job is None:
        cast(Job, form.instance).creation_source = CreationSource.API
    if not form.is_valid():
        raise FieldErrors(form_errors(form))
    return cast(Job, form.save())


@router.get("", response={200: Page[JobOut], **ERRORS})
def list_jobs(request: HttpRequest, params: Query[JobParams]) -> Page[JobOut]:
    """Your jobs, most recently updated first. `q` searches job titles and
    company names; `status`, `company` and `posting_url` (the same posting
    as this link, e.g. to check whether a posting is already saved) filter."""
    filters = JobFilters(
        query=params.q.strip(), status=params.status, company=params.company
    )
    jobs = job_list(api_user(request), filters)
    if posting_url := params.posting_url.strip():
        jobs = with_posting_url(jobs, posting_url)
    return page_of(with_skills(jobs), params, job_out)


@router.get("/{job_id}", response={200: JobOut, **ERRORS})
def get_job_detail(request: HttpRequest, job_id: uuid.UUID) -> JobOut:
    return job_out(get_job(api_user(request), job_id))


@router.post("", response={201: JobOut, **ERRORS})
def create_job(request: HttpRequest, payload: JobIn) -> tuple[int, JobOut]:
    """Add a job at one of your companies, or at a company named by
    `company_name` (created if you don't have it yet)."""
    user = api_user(request)
    # One transaction: if the job is refused, a company made for it is too.
    with transaction.atomic():
        company = resolve_company(user, payload.company, payload.company_name)
        data: FormValues = {
            **job_values(payload),
            "company": str(company.id),
            "skills": resolve_skills(payload.skills),
        }
        job = save_job(user, data)
        if payload.status is not None:
            _ = set_job_status(job, payload.status)
    return 201, job_out(get_job(user, job.id))


@router.patch("/{job_id}", response={200: JobOut, **ERRORS})
def update_job(request: HttpRequest, job_id: uuid.UUID, payload: JobPatch) -> JobOut:
    """Change one of your jobs; only the fields sent are changed. `skills`
    replaces the job's skills; a new `status` is added to its history."""
    user = api_user(request)
    job = get_job(user, job_id)
    sent = payload.model_fields_set
    if "status" in sent and payload.status is None:
        raise FieldErrors({"status": ["A job's status can't be removed."]})
    with transaction.atomic():
        data = current_values(job) | job_values(payload)
        if sent & {"company", "company_name"}:
            company = resolve_company(
                user,
                payload.company if "company" in sent else None,
                payload.company_name if "company_name" in sent else None,
            )
            data["company"] = str(company.id)
        if "skills" in sent:
            data["skills"] = resolve_skills(payload.skills)
        _ = save_job(user, data, job)
        if payload.status is not None:
            _ = set_job_status(job, payload.status)
    return job_out(get_job(user, job_id))
