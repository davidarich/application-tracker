"""Jobs that best match the skills on the user's resume.

A job's match is the share of its skills that are on the resume: a job
asking for four skills, three of which the user has, is a 75% match. Only
jobs the user hasn't applied to (no application at all, so ignored jobs are
left out too) with at least one matching skill are suggested.
"""

import uuid
from dataclasses import dataclass

from django.db.models import Count, ExpressionWrapper, F, FloatField, Prefetch, Q
from django.db.models.functions import Lower

from accounts.models import User

from .models import Job
from .ownership import active_skills, jobs_for

BEST_MATCHES_LIMIT = 10


@dataclass(frozen=True)
class SkillMatch:
    job: Job
    matched: list[str]  # the job's skills that are on the resume
    missing: list[str]  # the job's skills that aren't

    @property
    def total(self) -> int:
        return len(self.matched) + len(self.missing)

    @property
    def percent(self) -> int:
        return round(100 * len(self.matched) / self.total) if self.total else 0


def resume_skill_ids(user: User) -> set[uuid.UUID]:
    """The (not deleted) skills on the user's resume."""
    return {skill.id for skill in active_skills().filter(resumes__user_owner=user)}


def best_skill_matches(
    user: User, resume_skills: set[uuid.UUID], limit: int = BEST_MATCHES_LIMIT
) -> list[SkillMatch]:
    """The user's not-yet-applied jobs that best match `resume_skills`,
    highest match first; ties go to more matching skills, then newer jobs."""
    if not resume_skills:
        return []
    active = Q(skills__is_deleted=False)
    jobs = (
        jobs_for(user)
        .filter(applications__isnull=True)
        .annotate(
            skill_total=Count("skills", filter=active, distinct=True),
            skill_matched=Count(
                "skills", filter=active & Q(skills__in=resume_skills), distinct=True
            ),
        )
        .filter(skill_matched__gt=0)
        .annotate(
            match=ExpressionWrapper(
                F("skill_matched") * 1.0 / F("skill_total"), output_field=FloatField()
            )
        )
        .order_by("-match", "-skill_matched", "-date_added", "id")
        .select_related("company")
        .prefetch_related(
            Prefetch("skills", queryset=active_skills().order_by(Lower("name")))
        )[:limit]
    )
    return [
        SkillMatch(
            job=job,
            matched=[s.name for s in job.skills.all() if s.id in resume_skills],
            missing=[s.name for s in job.skills.all() if s.id not in resume_skills],
        )
        for job in jobs
    ]
