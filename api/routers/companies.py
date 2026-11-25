"""The user's companies: list, read, create and change."""

import uuid

from django.http import HttpRequest
from ninja import Query, Router

from tracker.models import CreationSource

from ..auth import api_user
from ..schemas import ERRORS, CompanyIn, CompanyOut, CompanyPatch, Page, SearchParams
from ..services import companies

router = Router(tags=["Companies"])


@router.get("", response={200: Page[CompanyOut], **ERRORS})
def list_companies(
    request: HttpRequest, params: Query[SearchParams]
) -> Page[CompanyOut]:
    """Your companies (not deleted), by name; `q` searches names."""
    return companies.list_companies(api_user(request), params)


@router.get("/{company_id}", response={200: CompanyOut, **ERRORS})
def get_company_detail(request: HttpRequest, company_id: uuid.UUID) -> CompanyOut:
    return companies.company_detail(api_user(request), company_id)


@router.post("", response={201: CompanyOut, **ERRORS})
def create_company(request: HttpRequest, payload: CompanyIn) -> tuple[int, CompanyOut]:
    """Add a company. Your company names are unique, ignoring case."""
    user = api_user(request)
    return 201, companies.create_company(user, payload, CreationSource.API)


@router.patch("/{company_id}", response={200: CompanyOut, **ERRORS})
def update_company(
    request: HttpRequest, company_id: uuid.UUID, payload: CompanyPatch
) -> CompanyOut:
    """Change one of your companies; only the fields sent are changed."""
    return companies.update_company(api_user(request), company_id, payload)
