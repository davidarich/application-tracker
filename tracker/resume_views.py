"""The Resume page: a summary, work history, skills, education and certifications.

The summary and skills are edited in place on the page. Work history,
education and certification entries each have add and edit pages, shared by
all three sections (see SECTIONS).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.http import request_user
from accounts.models import User

from .forms import (
    CertificationForm,
    EducationForm,
    ResumeSkillsForm,
    ResumeSummaryForm,
    WorkExperienceForm,
)
from .models import Certification, Education, ResumeEntry, WorkExperience
from .ownership import (
    certifications_for,
    deleted_certifications_for,
    deleted_education_for,
    deleted_work_history_for,
    education_for,
    resume_for,
    work_history_for,
)
from .undo import offer_undo

type EntryQuerySet = (
    QuerySet[WorkExperience] | QuerySet[Education] | QuerySet[Certification]
)


@dataclass(frozen=True)
class ResumeSection:
    """One of the resume's list sections, and how to add and edit its entries."""

    slug: str  # in URLs, and the section's anchor on the Resume page
    heading: str
    noun: str  # one entry, e.g. "position"
    form_class: type[forms.ModelForm]
    entries: Callable[[User], EntryQuerySet]  # the user's entries
    deleted: Callable[[User], EntryQuerySet]  # the user's soft-deleted entries

    @property
    def undo_kind(self) -> str:
        """How the undo of a delete in this section is remembered."""
        return f"resume-{self.slug}"

    def url(self) -> str:
        """The section on the Resume page."""
        return f"{reverse('tracker:resume')}#{self.slug}"


SECTIONS: dict[str, ResumeSection] = {
    section.slug: section
    for section in [
        ResumeSection(
            "work",
            "Work history",
            "position",
            WorkExperienceForm,
            work_history_for,
            deleted_work_history_for,
        ),
        ResumeSection(
            "education",
            "Education",
            "education",
            EducationForm,
            education_for,
            deleted_education_for,
        ),
        ResumeSection(
            "certifications",
            "Certifications",
            "certification",
            CertificationForm,
            certifications_for,
            deleted_certifications_for,
        ),
    ]
}


def section_or_404(slug: str) -> ResumeSection:
    section = SECTIONS.get(slug)
    if section is None:
        raise Http404("No such resume section.")
    return section


def entry_or_404(
    section: ResumeSection, request: HttpRequest, pk: uuid.UUID
) -> ResumeEntry:
    """One of the user's entries in `section`; anyone else's is a 404."""
    entry = section.entries(request_user(request)).filter(pk=pk).first()
    if entry is None:
        raise Http404("No such entry.")
    return entry


@login_required
def resume(request: HttpRequest) -> HttpResponse:
    """The user's resume. A POST saves the summary or the skills (a form each)."""
    user = request_user(request)
    current = resume_for(user)
    summary_form = ResumeSummaryForm(instance=current)
    skills_form = ResumeSkillsForm(instance=current)
    if request.method == "POST":
        part = request.POST.get("part")
        if part == "summary":
            summary_form = form = ResumeSummaryForm(request.POST, instance=current)
        elif part == "skills":
            skills_form = form = ResumeSkillsForm(request.POST, instance=current)
        else:
            return redirect("tracker:resume")
        if form.is_valid():
            _ = cast(object, form.save())
            messages.success(request, f"Saved your {part}.")
            return redirect(f"{reverse('tracker:resume')}#{part}")
    return render(
        request,
        "tracker/resume.html",
        {
            "resume": current,
            "summary_form": summary_form,
            "skills_form": skills_form,
            "work_history": work_history_for(user),
            "education": education_for(user),
            "certifications": certifications_for(user),
            "today": timezone.localdate(),
        },
    )


@login_required
def resume_file(request: HttpRequest) -> FileResponse:
    """The user's own last uploaded resume PDF (there's no way to ask for anyone else's)."""
    current = resume_for(request_user(request))
    if not current.file:
        raise Http404("No uploaded resume.")
    try:
        handle = current.file.open("rb")
    except FileNotFoundError:
        raise Http404("The resume is missing from storage.") from None
    response = FileResponse(
        handle,
        content_type="application/pdf",
        filename=current.file_name or "resume.pdf",
    )
    response["Cache-Control"] = "private, no-cache"
    return response


def entry_form_page(
    request: HttpRequest, section: ResumeSection, entry: ResumeEntry | None
) -> HttpResponse:
    """Add (entry is None) or edit one of the user's entries in `section`."""
    form = section.form_class(request.POST or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        saved = cast(ResumeEntry, form.save(commit=False))
        saved.user_owner = request_user(request)
        saved.save()
        messages.success(request, f"Saved {saved}.")
        return redirect(section.url())
    context: dict[str, object] = {"form": form, "section": section}
    if entry is None:
        context |= {
            "heading": f"Add {section.noun}",
            "submit_label": f"Add {section.noun}",
            "action": reverse("tracker:resume_entry_add", args=[section.slug]),
        }
    else:
        context |= {
            "heading": f"Edit {entry}",
            "entry_name": str(entry),
            "submit_label": "Save changes",
            "action": reverse(
                "tracker:resume_entry_edit", args=[section.slug, entry.id]
            ),
            "delete_action": reverse(
                "tracker:resume_entry_delete", args=[section.slug, entry.id]
            ),
        }
    return render(request, "tracker/resume_entry_form.html", context)


@login_required
def resume_entry_add(request: HttpRequest, section: str) -> HttpResponse:
    return entry_form_page(request, section_or_404(section), None)


@login_required
def resume_entry_edit(
    request: HttpRequest, section: str, pk: uuid.UUID
) -> HttpResponse:
    """Edit one of the user's entries; anyone else's is a 404."""
    found = section_or_404(section)
    return entry_form_page(request, found, entry_or_404(found, request, pk))


@login_required
@require_POST
def resume_entry_delete(
    request: HttpRequest, section: str, pk: uuid.UUID
) -> HttpResponse:
    """Soft-delete one of the user's entries (with an Undo button); anyone
    else's is a 404."""
    found = section_or_404(section)
    entry = entry_or_404(found, request, pk)
    entry.is_deleted, entry.deleted_at = True, timezone.now()
    entry.save(update_fields=["is_deleted", "deleted_at"])
    offer_undo(request, found.undo_kind, entry.id, str(entry))
    return redirect(found.url())


def section_for_undo(kind: str) -> ResumeSection | None:
    """The section a remembered undo kind ("resume-work"...) is for."""
    return next((s for s in SECTIONS.values() if s.undo_kind == kind), None)


def restore_entry(
    user: User, section: ResumeSection, record_id: uuid.UUID
) -> str | None:
    """Undelete one of the user's entries; return why not, if it can't be."""
    entry = section.deleted(user).filter(id=record_id).first()
    if entry is None:
        return "it's no longer deleted, or doesn't exist."
    entry.is_deleted, entry.deleted_at = False, None
    entry.save(update_fields=["is_deleted", "deleted_at"])
    return None


@login_required
@require_POST
def resume_entry_restore(
    request: HttpRequest, section: str, pk: uuid.UUID
) -> HttpResponse:
    """Restore one of the user's deleted entries (from Recently deleted)."""
    found = section_or_404(section)
    user = request_user(request)
    entry = found.deleted(user).filter(pk=pk).first()
    if entry is None:
        raise Http404("No such deleted entry.")
    name = str(entry)
    error = restore_entry(user, found, entry.id)
    if error:
        messages.error(request, f"Couldn't restore {name}: {error}")
    else:
        messages.success(request, f"Restored {name} to your resume.")
    return redirect("tracker:recently_deleted")


@dataclass(frozen=True)
class DeletedEntry:
    """A deleted resume entry, for the Recently deleted page."""

    section: ResumeSection
    entry: ResumeEntry

    @property
    def name(self) -> str:
        return str(self.entry)


def deleted_entries(user: User) -> list[DeletedEntry]:
    """All the user's deleted resume entries, newest first."""
    found = [
        DeletedEntry(section, entry)
        for section in SECTIONS.values()
        for entry in section.deleted(user)
    ]
    oldest = timezone.make_aware(datetime.min.replace(year=1970))
    return sorted(found, key=lambda item: item.entry.deleted_at or oldest, reverse=True)
