"""The shared skills list: anyone can read it; only staff add or change skills."""

import uuid
from typing import cast

from django.db.models import Q
from django.db.models.functions import Lower
from django.http import Http404
from ninja.errors import HttpError

from accounts.models import User
from tracker.forms import SkillForm
from tracker.models import CreationSource, Skill
from tracker.ownership import active_skills

from ..errors import FieldErrors, form_data, form_errors
from ..paging import page_of
from ..schemas import (
    CreationSourceValue,
    Page,
    SearchParams,
    SkillIn,
    SkillOut,
    SkillPatch,
)

STAFF_ONLY = "Only staff can add or change skills."


def require_staff(user: User) -> None:
    """Refuse (403) a change by anyone but staff."""
    if not user.is_staff:
        raise HttpError(403, STAFF_ONLY)


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


def list_skills(params: SearchParams) -> Page[SkillOut]:
    """The skills (not deleted), by name; `q` searches names and descriptions."""
    skills = active_skills()
    if query := params.q.strip():
        skills = skills.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    return page_of(skills.order_by(Lower("name"), "id"), params, skill_out)


def skill_detail(skill_id: uuid.UUID) -> SkillOut:
    return skill_out(get_skill(skill_id))


def create_skill(user: User, payload: SkillIn, source: CreationSource) -> SkillOut:
    """Add a skill (staff only). Names are unique, ignoring case."""
    require_staff(user)
    skill = save_skill(
        {"name": payload.name, "description": payload.description},
        Skill(creation_source=source),
    )
    return skill_out(skill)


def update_skill(user: User, skill_id: uuid.UUID, payload: SkillPatch) -> SkillOut:
    """Change a skill (staff only); only the fields sent are changed."""
    require_staff(user)
    skill = get_skill(skill_id)
    values = {"name": payload.name, "description": payload.description}
    data = {"name": skill.name, "description": skill.description} | {
        field: value
        for field, value in values.items()
        if field in payload.model_fields_set
    }
    return skill_out(save_skill(data, skill))
