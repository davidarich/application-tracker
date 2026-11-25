"""Which user owns each tracker record, and querysets limited to one user.

Companies and files have a user_owner. Everything else belongs to the owner of
its company: contacts and jobs directly, applications through their job, and
cover letters and status changes through their application. Owning only the
roots means ownership can never disagree between related records.

Views, reports and forms get tracker data only through the functions below, so
each user sees just their own records. Skills are the exception: they're shared
by everyone (see SHARED_MODELS).
"""

from django.db.models import Model, QuerySet

from accounts.models import User

from .models import (
    Application,
    ApplicationStatusChange,
    Certification,
    Company,
    Contact,
    CoverLetter,
    Education,
    File,
    Job,
    Resume,
    Skill,
    WorkExperience,
)

# Models shared by every user, with no owner: anyone can use any of them.
SHARED_MODELS: frozenset[type[Model]] = frozenset({Skill})

# Soft deletes: a record is hidden when it, its job or its company is
# deleted (so deleting a company hides its jobs, contacts and applications too).
ACTIVE_FILTERS: dict[type[Model], dict[str, bool]] = {
    Company: {"is_deleted": False},
    File: {},
    Resume: {},
    WorkExperience: {"is_deleted": False},
    Education: {"is_deleted": False},
    Certification: {"is_deleted": False},
    Contact: {"company__is_deleted": False},
    Job: {"is_deleted": False, "company__is_deleted": False},
    Application: {"job__is_deleted": False, "job__company__is_deleted": False},
    CoverLetter: {
        "application__job__is_deleted": False,
        "application__job__company__is_deleted": False,
    },
    ApplicationStatusChange: {
        "application__job__is_deleted": False,
        "application__job__company__is_deleted": False,
    },
}

# The lookup from each owned tracker model to its owning user.
OWNER_PATHS: dict[type[Model], str] = {
    Company: "user_owner",
    File: "user_owner",
    Resume: "user_owner",
    WorkExperience: "user_owner",
    Education: "user_owner",
    Certification: "user_owner",
    Contact: "company__user_owner",
    Job: "company__user_owner",
    Application: "job__company__user_owner",
    CoverLetter: "application__job__company__user_owner",
    ApplicationStatusChange: "application__job__company__user_owner",
}


def companies_for(user: User) -> QuerySet[Company]:
    return Company.objects.filter(
        **{OWNER_PATHS[Company]: user}, **ACTIVE_FILTERS[Company]
    )


def contacts_for(user: User) -> QuerySet[Contact]:
    return Contact.objects.filter(
        **{OWNER_PATHS[Contact]: user}, **ACTIVE_FILTERS[Contact]
    )


def jobs_for(user: User) -> QuerySet[Job]:
    return Job.objects.filter(**{OWNER_PATHS[Job]: user}, **ACTIVE_FILTERS[Job])


def applications_for(user: User) -> QuerySet[Application]:
    return Application.objects.filter(
        **{OWNER_PATHS[Application]: user}, **ACTIVE_FILTERS[Application]
    )


def cover_letters_for(user: User) -> QuerySet[CoverLetter]:
    return CoverLetter.objects.filter(
        **{OWNER_PATHS[CoverLetter]: user}, **ACTIVE_FILTERS[CoverLetter]
    )


def status_changes_for(user: User) -> QuerySet[ApplicationStatusChange]:
    return ApplicationStatusChange.objects.filter(
        **{OWNER_PATHS[ApplicationStatusChange]: user},
        **ACTIVE_FILTERS[ApplicationStatusChange],
    )


def files_for(user: User) -> QuerySet[File]:
    return File.objects.filter(**{OWNER_PATHS[File]: user})


def active_skills() -> QuerySet[Skill]:
    """The shared skills that haven't been (soft) deleted."""
    return Skill.objects.filter(is_deleted=False)


def deleted_companies_for(user: User) -> QuerySet[Company]:
    """`user`'s soft-deleted companies (for the Recently deleted page and restoring)."""
    return Company.objects.filter(**{OWNER_PATHS[Company]: user}, is_deleted=True)


def deleted_jobs_for(user: User) -> QuerySet[Job]:
    """`user`'s soft-deleted jobs (whether or not their company is deleted too)."""
    return Job.objects.filter(**{OWNER_PATHS[Job]: user}, is_deleted=True)


def deleted_skills() -> QuerySet[Skill]:
    """The shared skills that have been (soft) deleted."""
    return Skill.objects.filter(is_deleted=True)


def resume_for(user: User) -> Resume:
    """`user`'s resume (summary and skills), created empty on first use."""
    return Resume.objects.get_or_create(user_owner=user)[0]


def work_history_for(user: User) -> QuerySet[WorkExperience]:
    return WorkExperience.objects.filter(
        **{OWNER_PATHS[WorkExperience]: user}, **ACTIVE_FILTERS[WorkExperience]
    )


def education_for(user: User) -> QuerySet[Education]:
    return Education.objects.filter(
        **{OWNER_PATHS[Education]: user}, **ACTIVE_FILTERS[Education]
    )


def certifications_for(user: User) -> QuerySet[Certification]:
    return Certification.objects.filter(
        **{OWNER_PATHS[Certification]: user}, **ACTIVE_FILTERS[Certification]
    )


def deleted_work_history_for(user: User) -> QuerySet[WorkExperience]:
    """`user`'s soft-deleted positions (for Recently deleted and restoring)."""
    return WorkExperience.objects.filter(
        **{OWNER_PATHS[WorkExperience]: user}, is_deleted=True
    )


def deleted_education_for(user: User) -> QuerySet[Education]:
    return Education.objects.filter(**{OWNER_PATHS[Education]: user}, is_deleted=True)


def deleted_certifications_for(user: User) -> QuerySet[Certification]:
    return Certification.objects.filter(
        **{OWNER_PATHS[Certification]: user}, is_deleted=True
    )
