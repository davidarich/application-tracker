"""The user's companies: list, read, create and change."""

import uuid
from typing import cast

from django.db.models import Count, Q, QuerySet
from django.db.models.functions import Lower
from django.http import Http404, HttpRequest
from ninja import Query, Router

from accounts.models import User
from tracker.forms import CompanyForm, save_company_form
from tracker.models import Company, CreationSource
from tracker.ownership import companies_for

from ..auth import api_user
from ..errors import FieldErrors, form_data, form_errors
from ..paging import page_of
from ..schemas import (
    ERRORS,
    CompanyIn,
    CompanyOut,
    CompanyPatch,
    CreationSourceValue,
    Page,
    SearchParams,
)

router = Router(tags=["Companies"])


def companies_with_counts(user: User) -> QuerySet[Company]:
    """`user`'s companies, each annotated with job_count (jobs not deleted)."""
    return companies_for(user).annotate(
        job_count=Count("jobs", filter=Q(jobs__is_deleted=False))
    )


def company_out(company: Company) -> CompanyOut:
    return CompanyOut(
        id=company.id,
        name=company.name,
        website=company.website,
        mission_statement=company.mission_statement,
        is_staffing_agency=company.is_staffing_agency,
        job_count=cast(int, vars(company).get("job_count", 0)),
        date_added=company.date_added,
        creation_source=cast(CreationSourceValue, company.creation_source),
    )


def get_company(user: User, company_id: uuid.UUID) -> Company:
    """One of `user`'s companies (anyone else's is a 404, as if it didn't exist)."""
    company = companies_with_counts(user).filter(id=company_id).first()
    if company is None:
        raise Http404("No company with this ID.")
    return company


def company_values(payload: CompanyIn | CompanyPatch) -> dict[str, str]:
    """The form values a request sends (for a PATCH, only the fields it sent)."""
    values = {
        "name": payload.name,
        "website": payload.website,
        "mission_statement": payload.mission_statement,
        "is_staffing_agency": "true" if payload.is_staffing_agency else "false",
    }
    if isinstance(payload, CompanyIn):
        return values
    return {k: v for k, v in values.items() if k in payload.model_fields_set}


def save_company(
    user: User,
    company: Company,
    data: dict[str, str],
    renames: dict[str, str] | None = None,
) -> Company:
    """Validate and save `company` with the web app's form (including its
    check that the user's company names are unique)."""
    form = CompanyForm(form_data(data), instance=company)
    if not save_company_form(form, user):
        raise FieldErrors(form_errors(form, renames))
    return company


@router.get("", response={200: Page[CompanyOut], **ERRORS})
def list_companies(
    request: HttpRequest, params: Query[SearchParams]
) -> Page[CompanyOut]:
    """Your companies (not deleted), by name; `q` searches names."""
    companies = companies_with_counts(api_user(request))
    if query := params.q.strip():
        companies = companies.filter(name__icontains=query)
    return page_of(companies.order_by(Lower("name"), "id"), params, company_out)


@router.get("/{company_id}", response={200: CompanyOut, **ERRORS})
def get_company_detail(request: HttpRequest, company_id: uuid.UUID) -> CompanyOut:
    return company_out(get_company(api_user(request), company_id))


@router.post("", response={201: CompanyOut, **ERRORS})
def create_company(request: HttpRequest, payload: CompanyIn) -> tuple[int, CompanyOut]:
    """Add a company. Your company names are unique, ignoring case."""
    user = api_user(request)
    new = Company(user_owner=user, creation_source=CreationSource.API)
    company = save_company(user, new, company_values(payload))
    return 201, company_out(get_company(user, company.id))


@router.patch("/{company_id}", response={200: CompanyOut, **ERRORS})
def update_company(
    request: HttpRequest, company_id: uuid.UUID, payload: CompanyPatch
) -> CompanyOut:
    """Change one of your companies; only the fields sent are changed."""
    user = api_user(request)
    company = get_company(user, company_id)
    current = {
        "name": company.name,
        "website": company.website,
        "mission_statement": company.mission_statement,
        "is_staffing_agency": "true" if company.is_staffing_agency else "false",
    }
    _ = save_company(user, company, current | company_values(payload))
    return company_out(get_company(user, company_id))
