"""The user's jobs: list, read, create and change, including their status."""

import uuid

from django.http import HttpRequest
from ninja import Query, Router

from tracker.models import CreationSource

from ..auth import api_user
from ..schemas import ERRORS, JobIn, JobOut, JobParams, JobPatch, Page
from ..services import jobs

router = Router(tags=["Jobs"])


@router.get("", response={200: Page[JobOut], **ERRORS})
def list_jobs(request: HttpRequest, params: Query[JobParams]) -> Page[JobOut]:
    """Your jobs, most recently updated first. `q` searches job titles and
    company names; `status`, `company` and `posting_url` (the same posting
    as this link, e.g. to check whether a posting is already saved) filter."""
    return jobs.list_jobs(api_user(request), params)


@router.get("/{job_id}", response={200: JobOut, **ERRORS})
def get_job_detail(request: HttpRequest, job_id: uuid.UUID) -> JobOut:
    return jobs.job_detail(api_user(request), job_id)


@router.post("", response={201: JobOut, **ERRORS})
def create_job(request: HttpRequest, payload: JobIn) -> tuple[int, JobOut]:
    """Add a job at one of your companies, or at a company named by
    `company_name` (created if you don't have it yet)."""
    return 201, jobs.create_job(api_user(request), payload, CreationSource.API)


@router.patch("/{job_id}", response={200: JobOut, **ERRORS})
def update_job(request: HttpRequest, job_id: uuid.UUID, payload: JobPatch) -> JobOut:
    """Change one of your jobs; only the fields sent are changed. `skills`
    replaces the job's skills; a new `status` is added to its history."""
    return jobs.update_job(api_user(request), job_id, payload, CreationSource.API)
