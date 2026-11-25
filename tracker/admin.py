from typing import final, override

from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

from .admin_ownership import OwnedModelAdmin, OwnedStackedInline, OwnedTabularInline
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


@final
class ContactInline(OwnedTabularInline[Contact]):
    model = Contact
    extra = 0
    fields = ["name", "email", "phone_number", "linkedin_url"]
    show_change_link = True


@final
class JobInline(OwnedTabularInline[Job]):
    model = Job
    extra = 0
    fields = [
        "title",
        "location_city",
        "location_state",
        "workplace_type",
        "posting_url",
    ]
    show_change_link = True


@admin.register(Company)
@final
class CompanyAdmin(OwnedModelAdmin[Company]):
    list_display = ["name", "website", "is_staffing_agency", "is_deleted", "date_added"]
    list_filter = ["is_deleted", "is_staffing_agency"]
    search_fields = ["name"]
    readonly_fields = ["id", "date_added"]
    inlines = [ContactInline, JobInline]


@admin.register(Contact)
@final
class ContactAdmin(OwnedModelAdmin[Contact]):
    list_display = ["name", "company", "email", "phone_number", "linkedin_url"]
    # RelatedOnly lists just the companies in the (owner-limited) records, so
    # the filter never shows other users' companies.
    list_filter = [("company", admin.RelatedOnlyFieldListFilter)]
    search_fields = ["name", "email", "company__name"]
    autocomplete_fields = ["company"]
    readonly_fields = ["id"]


@final
class ApplicationInline(OwnedTabularInline[Application]):
    model = Application
    extra = 0
    fields = ["status"]
    show_change_link = True


@admin.register(Job)
@final
class JobAdmin(OwnedModelAdmin[Job]):
    list_display = [
        "title",
        "company",
        "location",
        "workplace_type",
        "salary_min",
        "salary_max",
        "is_deleted",
        "date_added",
    ]
    list_filter = [
        "is_deleted",
        "workplace_type",
        ("company", admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = ["title", "company__name", "location_city", "location_state"]
    autocomplete_fields = ["company", "skills"]
    readonly_fields = ["id", "date_added"]
    inlines = [ApplicationInline]


@final
class CoverLetterInline(OwnedStackedInline[CoverLetter]):
    model = CoverLetter
    extra = 0
    fields = ["contents"]


@final
class StatusChangeInline(OwnedTabularInline[ApplicationStatusChange]):
    """Read-only status history; entries are recorded by Application.save()."""

    model = ApplicationStatusChange
    extra = 0
    fields = ["status", "changed_at"]
    readonly_fields = ["status", "changed_at"]
    can_delete = False
    verbose_name_plural = "status history"

    @override
    def has_add_permission(
        self, request: HttpRequest, obj: Model | None = None
    ) -> bool:
        return False


@admin.register(Application)
@final
class ApplicationAdmin(OwnedModelAdmin[Application]):
    list_display = ["job", "status", "updated_at"]
    list_filter = ["status", ("job__company", admin.RelatedOnlyFieldListFilter)]
    search_fields = ["job__title", "job__company__name"]
    autocomplete_fields = ["job"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [CoverLetterInline, StatusChangeInline]


@admin.register(CoverLetter)
@final
class CoverLetterAdmin(OwnedModelAdmin[CoverLetter]):
    list_display = ["__str__", "application"]
    search_fields = [
        "contents",
        "application__job__title",
        "application__job__company__name",
    ]
    autocomplete_fields = ["application"]
    readonly_fields = ["id"]


@admin.register(File)
@final
class FileAdmin(OwnedModelAdmin[File]):
    list_display = ["name", "path"]
    search_fields = ["name"]
    readonly_fields = ["id"]


@admin.register(Resume)
@final
class ResumeAdmin(OwnedModelAdmin[Resume]):
    list_display = ["user_owner", "updated_at"]
    filter_horizontal = ["skills"]
    readonly_fields = ["id", "updated_at"]


@admin.register(WorkExperience)
@final
class WorkExperienceAdmin(OwnedModelAdmin[WorkExperience]):
    list_display = ["title", "employer", "start_date", "end_date", "is_deleted"]
    list_filter = ["is_deleted"]
    search_fields = ["title", "employer"]
    readonly_fields = ["id"]


@admin.register(Education)
@final
class EducationAdmin(OwnedModelAdmin[Education]):
    list_display = ["institution", "degree", "field_of_study", "end_date", "is_deleted"]
    list_filter = ["is_deleted"]
    search_fields = ["institution", "degree", "field_of_study"]
    readonly_fields = ["id"]


@admin.register(Certification)
@final
class CertificationAdmin(OwnedModelAdmin[Certification]):
    list_display = ["name", "issuer", "issued_on", "expires_on", "is_deleted"]
    list_filter = ["is_deleted"]
    search_fields = ["name", "issuer"]
    readonly_fields = ["id"]


@admin.register(Skill)
@final
class SkillAdmin(admin.ModelAdmin[Skill]):
    """Skills are shared by all users, so this isn't limited by owner."""

    list_display = ["name", "description", "is_deleted"]
    list_filter = ["is_deleted"]
    search_fields = ["name", "description"]
    readonly_fields = ["id"]
