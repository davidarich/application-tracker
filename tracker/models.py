import uuid
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import PurePath
from typing import ClassVar, cast, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from django.db.models.expressions import OrderBy
from django.db.models.functions import Lower
from django.utils import timezone

from accounts.models import User

# The user model's app label and name, for foreign keys (settings are untyped).
USER_MODEL = cast(str, settings.AUTH_USER_MODEL)


class Company(models.Model):
    """A company a user tracks. Companies (and files) are the roots of ownership:
    contacts, jobs, applications, cover letters and status changes belong to the
    user who owns their company (see tracker/ownership.py)."""

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    user_owner: models.ForeignKey[User] = models.ForeignKey(
        USER_MODEL, on_delete=models.CASCADE, related_name="companies"
    )
    name: models.CharField[str] = models.CharField(max_length=200)
    website: models.URLField[str] = models.URLField(blank=True)
    is_staffing_agency: models.BooleanField[bool] = models.BooleanField(default=False)
    mission_statement: models.TextField[str] = models.TextField(blank=True)
    # Soft delete: hidden everywhere in the app (still visible in the admin).
    is_deleted: models.BooleanField[bool] = models.BooleanField(
        default=False, db_index=True
    )
    # When it was soft-deleted (for the Recently deleted page); cleared on restore.
    deleted_at: models.DateTimeField[datetime | None] = models.DateTimeField(
        null=True, blank=True
    )
    date_added: models.DateTimeField[datetime] = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]
        verbose_name_plural: ClassVar[str] = "companies"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # Each user's company names are unique, ignoring case; different
            # users can track companies with the same name. Deleted companies
            # don't count, so a deleted company's name can be used again.
            models.UniqueConstraint(
                Lower("name"),
                "user_owner",
                condition=models.Q(is_deleted=False),
                name="tracker_company_owner_name_ci_unique",
                violation_error_message="You already have a company with this name.",
            ),
        ]

    @override
    def __str__(self) -> str:
        return self.name


class Contact(models.Model):
    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    company: models.ForeignKey[Company] = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="contacts"
    )
    name: models.CharField[str] = models.CharField(max_length=200)
    email: models.EmailField[str] = models.EmailField(blank=True)
    phone_number: models.CharField[str] = models.CharField(max_length=30, blank=True)
    linkedin_url: models.URLField[str] = models.URLField(
        "LinkedIn profile URL", blank=True
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]

    @override
    def __str__(self) -> str:
        return f"{self.name} ({self.company})"


class Skill(models.Model):
    """A skill a job can call for, e.g. Python or Kubernetes.

    Skills are shared by all users (they have no owner), so every user picks
    from the same list.
    """

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    name: models.CharField[str] = models.CharField(max_length=100)
    description: models.TextField[str] = models.TextField(blank=True)
    # Soft delete: hidden everywhere in the app (still visible in the admin).
    is_deleted: models.BooleanField[bool] = models.BooleanField(
        default=False, db_index=True
    )
    # When it was soft-deleted (for the Recently deleted page); cleared on restore.
    deleted_at: models.DateTimeField[datetime | None] = models.DateTimeField(
        null=True, blank=True
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # One skill per name, ignoring case ("Python" and "python" are the
            # same). Deleted skills don't count, so their names can be used again.
            models.UniqueConstraint(
                Lower("name"),
                condition=models.Q(is_deleted=False),
                name="tracker_skill_name_ci_unique",
                violation_error_message="A skill with this name already exists.",
            ),
        ]

    @override
    def __str__(self) -> str:
        return self.name


class Job(models.Model):
    class WorkplaceType(models.TextChoices):
        IN_OFFICE = "in_office", "In office"
        HYBRID = "hybrid", "Hybrid"
        REMOTE = "remote", "Remote"

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    company: models.ForeignKey[Company] = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="jobs"
    )
    skills: models.ManyToManyField[Skill, "Job"] = models.ManyToManyField(
        Skill, blank=True, related_name="jobs"
    )
    title: models.CharField[str] = models.CharField(max_length=200)
    posting_url: models.URLField[str] = models.URLField(blank=True)
    location_city: models.CharField[str] = models.CharField(
        "city", max_length=100, blank=True
    )
    location_state: models.CharField[str] = models.CharField(
        "state / region",
        max_length=100,
        blank=True,
        help_text="State, province or country, e.g. WA, Ontario or Germany.",
    )
    workplace_type: models.CharField[str] = models.CharField(
        max_length=20,
        choices=WorkplaceType.choices,
        blank=True,
        help_text="Leave blank if the posting doesn't say.",
    )
    description: models.TextField[str] = models.TextField(blank=True)
    salary_min: models.PositiveIntegerField[int | None] = models.PositiveIntegerField(
        null=True, blank=True
    )
    salary_max: models.PositiveIntegerField[int | None] = models.PositiveIntegerField(
        null=True, blank=True
    )
    # Soft delete: hidden everywhere in the app (still visible in the admin).
    is_deleted: models.BooleanField[bool] = models.BooleanField(
        default=False, db_index=True
    )
    # When it was soft-deleted (for the Recently deleted page); cleared on restore.
    deleted_at: models.DateTimeField[datetime | None] = models.DateTimeField(
        null=True, blank=True
    )
    date_added: models.DateTimeField[datetime] = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-date_added"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(
                    salary_max__isnull=True,
                    salary_min__isnull=True,
                    salary_min__lte=models.F("salary_max"),
                    _connector=models.Q.OR,
                ),
                name="tracker_job_salary_range_valid",
                violation_error_message="Minimum salary can't exceed maximum salary.",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"{self.title} at {self.company}"

    @property
    def location(self) -> str:
        """City and state for display, e.g. "Seattle, WA"; blank if neither is set."""
        return ", ".join(
            part for part in (self.location_city, self.location_state) if part
        )


class Application(models.Model):
    class Status(models.TextChoices):
        APPLIED = "applied"
        RESPONDED = "responded"
        INTERVIEWING = "interviewing"
        OFFER = "offer"
        CLOSED = "closed"
        # The user decided not to pursue the job (it was never applied for).
        IGNORED = "ignored"

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    job: models.ForeignKey[Job] = models.ForeignKey(
        Job, on_delete=models.CASCADE, related_name="applications"
    )
    status: models.CharField[str] = models.CharField(
        max_length=20, choices=Status.choices, default=Status.APPLIED
    )
    created_at: models.DateTimeField[datetime] = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField[datetime] = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]

    @override
    def __str__(self) -> str:
        return f"{self.job} ({self.Status(self.status).label})"

    @override
    def save(
        self,
        force_insert: bool = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Save, recording an ApplicationStatusChange when the status is new or changed.

        Bulk operations such as QuerySet.update() bypass save() and so are not
        recorded; change statuses through save() to keep the history complete.
        """
        if update_fields is not None:
            update_fields = list(update_fields)
        status_may_change = update_fields is None or "status" in update_fields
        with transaction.atomic(using=using):
            previous_status: str | None = None
            if status_may_change and not self._state.adding:
                previous_status = (
                    Application.objects.using(using)
                    .filter(id=self.id)
                    .values_list("status", flat=True)
                    .first()
                )
            super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=using,
                update_fields=update_fields,
            )
            if status_may_change and self.status != previous_status:
                _ = ApplicationStatusChange.objects.using(using).create(
                    application=self, status=self.status
                )


class ApplicationStatusChange(models.Model):
    """A status an application entered, and when: its full history is kept so
    past days can be reported on (e.g. the dashboard's status chart)."""

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    application: models.ForeignKey[Application] = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="status_changes"
    )
    status: models.CharField[str] = models.CharField(
        max_length=20, choices=Application.Status.choices
    )
    changed_at: models.DateTimeField[datetime] = models.DateTimeField(
        default=timezone.now, db_index=True
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["changed_at"]
        get_latest_by: ClassVar[str] = "changed_at"

    @override
    def __str__(self) -> str:
        label = Application.Status(self.status).label
        return f"{self.application}: {label} on {self.changed_at:%Y-%m-%d %H:%M}"


class CoverLetter(models.Model):
    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    application: models.OneToOneField[Application] = models.OneToOneField(
        Application, on_delete=models.CASCADE, related_name="cover_letter"
    )
    contents: models.TextField[str] = models.TextField()

    @override
    def __str__(self) -> str:
        return f"Cover letter for {self.application.job}"


def file_upload_path(instance: "File", filename: str) -> str:
    """Store uploads as files/<owner's id>/<random id>.<extension>.

    A random name keeps the original filename (and so anything guessable) out
    of the path, and avoids clashes; the display name is kept in File.name.
    """
    extension = PurePath(filename).suffix.lower()
    return f"files/{instance.user_owner.id}/{uuid.uuid4().hex}{extension}"


class File(models.Model):
    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    user_owner: models.ForeignKey[User] = models.ForeignKey(
        USER_MODEL, on_delete=models.CASCADE, related_name="files"
    )
    name: models.CharField[str] = models.CharField(max_length=255)
    # Stored as a path relative to MEDIA_ROOT (the uploads folder). Files are
    # only served by tracker.views.download_file, which checks ownership.
    path: models.FileField = models.FileField(
        upload_to=file_upload_path, max_length=500
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]

    @override
    def __str__(self) -> str:
        return self.name


# --- Resume ------------------------------------------------------------------------
# Each user has one resume (summary and skills) and any number of work history,
# education and certification entries. Like companies and files, these are
# roots of ownership: each has a user_owner.


def resume_upload_path(instance: "Resume", _filename: str) -> str:
    """Store uploaded resumes as resumes/<user id>/<random id>.pdf.

    A random name keeps the original file name (shown to the user, and kept
    in Resume.file_name) out of the path. Files are only served by
    tracker.resume_views.resume_file, which serves the user's own.
    """
    return f"resumes/{instance.user_owner.id}/{uuid.uuid4().hex}.pdf"


class Resume(models.Model):
    """A user's resume summary and skills, and the last resume PDF they
    uploaded to fill it in from. The entries are separate models."""

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    user_owner: models.OneToOneField[User] = models.OneToOneField(
        USER_MODEL, on_delete=models.CASCADE, related_name="resume"
    )
    summary: models.TextField[str] = models.TextField(blank=True)
    skills: models.ManyToManyField[Skill, "Resume"] = models.ManyToManyField(
        Skill, blank=True, related_name="resumes"
    )
    updated_at: models.DateTimeField[datetime] = models.DateTimeField(auto_now=True)
    # The last uploaded resume PDF (each upload replaces the one before).
    file: models.FileField = models.FileField(
        upload_to=resume_upload_path, max_length=500, blank=True
    )
    file_name: models.CharField[str] = models.CharField(max_length=255, blank=True)
    file_uploaded_at: models.DateTimeField[datetime | None] = models.DateTimeField(
        null=True, blank=True
    )

    @override
    def __str__(self) -> str:
        return f"Resume of {self.user_owner}"


def check_date_range(start: date | None, end: date | None, end_field: str) -> None:
    """An entry can't end before it starts."""
    if start and end and end < start:
        raise ValidationError({end_field: "This can't be before the start date."})


class ResumeEntry(models.Model):
    """Fields shared by work history, education and certification entries."""

    id: models.UUIDField[uuid.UUID] = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    user_owner: models.ForeignKey[User] = models.ForeignKey(
        USER_MODEL, on_delete=models.CASCADE, related_name="%(class)s_entries"
    )
    # Soft delete: hidden everywhere in the app (still visible in the admin).
    is_deleted: models.BooleanField[bool] = models.BooleanField(
        default=False, db_index=True
    )
    # When it was soft-deleted (for the Recently deleted page); cleared on restore.
    deleted_at: models.DateTimeField[datetime | None] = models.DateTimeField(
        null=True, blank=True
    )

    class Meta:
        abstract: ClassVar[bool] = True


class WorkExperience(ResumeEntry):
    """A position in the user's work history. No end date means it's current;
    no employer means a career break (a sabbatical, medical leave...)."""

    title: models.CharField[str] = models.CharField("Job title", max_length=200)
    # Optional, for career breaks like a sabbatical or medical leave.
    employer: models.CharField[str] = models.CharField(max_length=200, blank=True)
    location: models.CharField[str] = models.CharField(max_length=200, blank=True)
    start_date: models.DateField[date] = models.DateField()
    end_date: models.DateField[date | None] = models.DateField(null=True, blank=True)
    description: models.TextField[str] = models.TextField(blank=True)

    class Meta(ResumeEntry.Meta):
        # Current positions first, then the most recent.
        ordering: ClassVar[list[str | OrderBy]] = [
            F("end_date").desc(nulls_first=True),
            "-start_date",
        ]
        verbose_name: ClassVar[str] = "work experience"
        verbose_name_plural: ClassVar[str] = "work history"

    @override
    def clean(self) -> None:
        check_date_range(self.start_date, self.end_date, "end_date")

    @override
    def __str__(self) -> str:
        return f"{self.title} at {self.employer}" if self.employer else self.title


class Education(ResumeEntry):
    """A school, degree or course of study."""

    institution: models.CharField[str] = models.CharField(max_length=200)
    degree: models.CharField[str] = models.CharField(max_length=200, blank=True)
    field_of_study: models.CharField[str] = models.CharField(max_length=200, blank=True)
    start_date: models.DateField[date | None] = models.DateField(null=True, blank=True)
    end_date: models.DateField[date | None] = models.DateField(null=True, blank=True)
    # Still studying: end_date (if any) is when they expect to finish.
    in_progress: models.BooleanField[bool] = models.BooleanField(
        "Still in progress", default=False
    )
    description: models.TextField[str] = models.TextField(blank=True)

    class Meta(ResumeEntry.Meta):
        ordering: ClassVar[list[str | OrderBy]] = [
            F("end_date").desc(nulls_first=True),
            F("start_date").desc(nulls_last=True),
        ]
        verbose_name_plural: ClassVar[str] = "education"

    @override
    def clean(self) -> None:
        check_date_range(self.start_date, self.end_date, "end_date")

    @override
    def __str__(self) -> str:
        return self.institution


class Certification(ResumeEntry):
    """A certification or license, e.g. AWS Solutions Architect."""

    name: models.CharField[str] = models.CharField(max_length=200)
    issuer: models.CharField[str] = models.CharField(
        "Issuing organization", max_length=200, blank=True
    )
    issued_on: models.DateField[date | None] = models.DateField(
        "Issue date", null=True, blank=True
    )
    expires_on: models.DateField[date | None] = models.DateField(
        "Expiration date", null=True, blank=True
    )
    # Still working towards it: issued_on (if any) is when they expect to finish.
    in_progress: models.BooleanField[bool] = models.BooleanField(
        "In progress", default=False
    )
    credential_id: models.CharField[str] = models.CharField(
        "Credential ID", max_length=200, blank=True
    )
    credential_url: models.URLField[str] = models.URLField("Credential URL", blank=True)

    class Meta(ResumeEntry.Meta):
        ordering: ClassVar[list[str | OrderBy]] = [
            F("issued_on").desc(nulls_last=True),
            "name",
        ]

    @override
    def clean(self) -> None:
        check_date_range(self.issued_on, self.expires_on, "expires_on")

    @override
    def __str__(self) -> str:
        return self.name
