"""The shared skills list: anyone can read it; only staff add or change skills."""

import uuid

from django.http import HttpRequest
from ninja import Query, Router

from tracker.models import CreationSource

from ..auth import api_user
from ..schemas import ERRORS, Page, SearchParams, SkillIn, SkillOut, SkillPatch
from ..services import skills

router = Router(tags=["Skills"])


@router.get("", response={200: Page[SkillOut], **ERRORS})
def list_skills(request: HttpRequest, params: Query[SearchParams]) -> Page[SkillOut]:
    """The skills (not deleted), by name; `q` searches names and descriptions."""
    _ = api_user(request)  # any API user can read the shared skills
    return skills.list_skills(params)


@router.get("/{skill_id}", response={200: SkillOut, **ERRORS})
def get_skill_detail(request: HttpRequest, skill_id: uuid.UUID) -> SkillOut:
    _ = api_user(request)
    return skills.skill_detail(skill_id)


@router.post("", response={201: SkillOut, **ERRORS})
def create_skill(request: HttpRequest, payload: SkillIn) -> tuple[int, SkillOut]:
    """Add a skill (staff only). Names are unique, ignoring case."""
    return 201, skills.create_skill(api_user(request), payload, CreationSource.API)


@router.patch("/{skill_id}", response={200: SkillOut, **ERRORS})
def update_skill(
    request: HttpRequest, skill_id: uuid.UUID, payload: SkillPatch
) -> SkillOut:
    """Change a skill (staff only); only the fields sent are changed."""
    return skills.update_skill(api_user(request), skill_id, payload)
