"""The shared skills list: anyone can read it; only staff add or change skills."""

import uuid
from typing import cast

from django.db.models import Q
from django.db.models.functions import Lower
from django.http import Http404, HttpRequest
from ninja import Query, Router

from tracker.forms import SkillForm
from tracker.models import CreationSource, Skill
from tracker.ownership import active_skills

from ..auth import api_user, require_staff
from ..errors import FieldErrors, form_data, form_errors
from ..paging import page_of
from ..schemas import (
    ERRORS,
    CreationSourceValue,
    Page,
    SearchParams,
    SkillIn,
    SkillOut,
    SkillPatch,
)

router = Router(tags=["Skills"])


def skill_out(skill: Skill) -> SkillOut:
    return SkillOut(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        creation_source=cast(CreationSourceValue, skill.creation_source),
    )


def get_skill(skill_id: uuid.UUID) -> Skill:
    skill = active_skills().filter(id=skill_id).first()
    if skill is None:
        raise Http404("No skill with this ID.")
    return skill


def save_skill(data: dict[str, str], skill: Skill | None = None) -> Skill:
    form = SkillForm(form_data(data), instance=skill)
    if not form.is_valid():
        raise FieldErrors(form_errors(form))
    return cast(Skill, form.save())


@router.get("", response={200: Page[SkillOut], **ERRORS})
def list_skills(request: HttpRequest, params: Query[SearchParams]) -> Page[SkillOut]:
    """The skills (not deleted), by name; `q` searches names and descriptions."""
    _ = api_user(request)  # any API user can read the shared skills
    skills = active_skills()
    if query := params.q.strip():
        skills = skills.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    return page_of(skills.order_by(Lower("name"), "id"), params, skill_out)


@router.get("/{skill_id}", response={200: SkillOut, **ERRORS})
def get_skill_detail(request: HttpRequest, skill_id: uuid.UUID) -> SkillOut:
    _ = api_user(request)
    return skill_out(get_skill(skill_id))


@router.post("", response={201: SkillOut, **ERRORS})
def create_skill(request: HttpRequest, payload: SkillIn) -> tuple[int, SkillOut]:
    """Add a skill (staff only). Names are unique, ignoring case."""
    _ = require_staff(request)
    skill = save_skill(
        {"name": payload.name, "description": payload.description},
        Skill(creation_source=CreationSource.API),
    )
    return 201, skill_out(skill)


@router.patch("/{skill_id}", response={200: SkillOut, **ERRORS})
def update_skill(
    request: HttpRequest, skill_id: uuid.UUID, payload: SkillPatch
) -> SkillOut:
    """Change a skill (staff only); only the fields sent are changed."""
    _ = require_staff(request)
    skill = get_skill(skill_id)
    values = {"name": payload.name, "description": payload.description}
    data = {"name": skill.name, "description": skill.description} | {
        field: value
        for field, value in values.items()
        if field in payload.model_fields_set
    }
    return skill_out(save_skill(data, skill))
