"""Filling in the resume from a PDF: upload, then review, then add.

The PDF is parsed with rules (tracker/resume_import) and kept with the
user's resume (uploads/resumes/, replacing the last upload; see
Resume.file). The parsed entries are kept in the session until the user
reviews them: no entries are saved until they choose what to add on the
review page, where each entry is an editable form (the same forms as adding
an entry by hand).
"""

from dataclasses import dataclass
from datetime import date
from pathlib import PurePath
from typing import cast

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models.functions import Lower
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.http import request_user
from accounts.models import User

from .forms import (
    CertificationForm,
    EducationForm,
    ResumeUploadForm,
    WorkExperienceForm,
)
from .models import Resume, ResumeEntry
from .ownership import (
    active_skills,
    certifications_for,
    education_for,
    resume_for,
    work_history_for,
)
from .resume_import import (
    CertificationEntry,
    EducationEntry,
    ResumeExtraction,
    ResumeReadError,
    SkillOption,
    WorkEntry,
    extract_lines,
    parse_resume,
)
from .resume_import.session import from_session, to_session

SESSION_KEY = "resume_import"

type Initial = dict[str, str | date | bool | None]


@login_required
def resume_import(request: HttpRequest) -> HttpResponse:
    """Upload a resume PDF; it's parsed, then reviewed on the next page."""
    form = ResumeUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = cast(bytes, form.cleaned_data["file"])
        try:
            lines = extract_lines(data)
        except ResumeReadError as error:
            form.add_error("file", str(error))
        else:
            upload = cast(UploadedFile, request.FILES["file"])
            save_uploaded_resume(
                resume_for(request_user(request)),
                data,
                PurePath(upload.name or "resume.pdf").name,
            )
            skills = [
                SkillOption(str(skill.id), skill.name)
                for skill in active_skills().order_by(Lower("name"))
            ]
            request.session[SESSION_KEY] = to_session(parse_resume(lines, skills))
            return redirect("tracker:resume_import_review")
    return render(request, "tracker/resume_import.html", {"form": form})


def save_uploaded_resume(resume: Resume, data: bytes, file_name: str) -> None:
    """Keep an uploaded resume PDF with the user's resume, replacing (and
    deleting) the one uploaded before."""
    old_name = resume.file.name
    resume.file.save("resume.pdf", ContentFile(data), save=False)
    resume.file_name = file_name[:255]
    resume.file_uploaded_at = timezone.now()
    resume.save(update_fields=["file", "file_name", "file_uploaded_at", "updated_at"])
    if old_name and old_name != resume.file.name:
        default_storage.delete(old_name)  # don't leave the old file behind


@dataclass
class ReviewItem:
    """One parsed entry on the review page."""

    prefix: str
    form: forms.ModelForm
    include: bool
    uncertain: bool
    duplicate: bool


def work_initial(entry: WorkEntry) -> Initial:
    return {
        "title": entry.title,
        "employer": entry.employer,
        "location": entry.location,
        "start_date": entry.start_date,
        "end_date": entry.end_date,
        "description": entry.description,
    }


def education_initial(entry: EducationEntry) -> Initial:
    return {
        "institution": entry.institution,
        "degree": entry.degree,
        "field_of_study": entry.field_of_study,
        "start_date": entry.start_date,
        "end_date": entry.end_date,
        "in_progress": entry.in_progress,
        "description": entry.description,
    }


def certification_initial(entry: CertificationEntry) -> Initial:
    return {
        "name": entry.name,
        "issuer": entry.issuer,
        "issued_on": entry.issued_on,
        "expires_on": entry.expires_on,
        "in_progress": entry.in_progress,
        "credential_id": entry.credential_id,
    }


def review_item(
    form_class: type[forms.ModelForm],
    prefix: str,
    initial: Initial,
    uncertain: bool,
    duplicate: bool,
    data: QueryDict | None,
) -> ReviewItem:
    """An entry's form: bound to what was posted if it's being added, else
    unbound (so entries left out don't show errors), showing the latest values."""
    include = (f"{prefix}-include" in data) if data is not None else not duplicate
    if data is not None and include:
        form = form_class(data, prefix=prefix)
    else:
        if data is not None:
            initial = {name: data.get(f"{prefix}-{name}", "") for name in initial}
        form = form_class(prefix=prefix, initial=initial)
    for field in form.fields.values():
        if "autofocus" in field.widget.attrs:  # many forms share the page
            del field.widget.attrs["autofocus"]
    return ReviewItem(prefix, form, include, uncertain, duplicate)


def build_items(
    user: User, data: QueryDict | None, extraction: ResumeExtraction
) -> tuple[list[ReviewItem], list[ReviewItem], list[ReviewItem]]:
    """The review page's work history, education and certification entries.
    Entries that look like ones already on the resume start unticked."""
    work = [
        review_item(
            WorkExperienceForm,
            f"work-{index}",
            work_initial(entry),
            entry.uncertain,
            work_history_for(user)
            .filter(
                title__iexact=entry.title,
                employer__iexact=entry.employer,
                start_date=entry.start_date,
            )
            .exists(),
            data,
        )
        for index, entry in enumerate(extraction.work)
    ]
    education = [
        review_item(
            EducationForm,
            f"education-{index}",
            education_initial(entry),
            entry.uncertain,
            bool(entry.institution)
            and education_for(user)
            .filter(institution__iexact=entry.institution, degree__iexact=entry.degree)
            .exists(),
            data,
        )
        for index, entry in enumerate(extraction.education)
    ]
    certifications = [
        review_item(
            CertificationForm,
            f"certification-{index}",
            certification_initial(entry),
            entry.uncertain,
            certifications_for(user).filter(name__iexact=entry.name).exists(),
            data,
        )
        for index, entry in enumerate(extraction.certifications)
    ]
    return work, education, certifications


def counted(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


@login_required
def resume_import_review(request: HttpRequest) -> HttpResponse:
    """Review what was found in the uploaded resume, and add the chosen parts."""
    user = request_user(request)
    extraction = from_session(request.session.get(SESSION_KEY))
    if extraction is None:
        messages.info(request, "Upload your resume to fill in your resume from it.")
        return redirect("tracker:resume_import")
    current = resume_for(user)
    data = request.POST if request.method == "POST" else None
    work, education, certifications = build_items(user, data, extraction)
    found_skills = list(
        active_skills().filter(id__in=extraction.skill_ids).order_by(Lower("name"))
    )
    existing_skill_ids = {str(skill.id) for skill in current.skills.all()}
    if data is None:
        summary = extraction.summary
        replace_summary = bool(extraction.summary) and not current.summary.strip()
        chosen_skill_ids = {
            str(skill.id) for skill in found_skills
        } - existing_skill_ids
    else:
        summary = data.get("summary", "").strip()
        replace_summary = "replace_summary" in data
        chosen_skill_ids = set(data.getlist("skills")) - existing_skill_ids

    if data is not None:
        chosen = [item for item in [*work, *education, *certifications] if item.include]
        valid = [
            item.form.is_valid() for item in chosen
        ]  # validate them all, for errors
        if all(valid):
            skills_to_add = [
                skill for skill in found_skills if str(skill.id) in chosen_skill_ids
            ]
            with transaction.atomic():
                for item in chosen:
                    entry = cast(ResumeEntry, item.form.save(commit=False))
                    entry.user_owner = user
                    entry.save()
                if replace_summary and summary:
                    current.summary = summary
                    current.save()
                if skills_to_add:
                    current.skills.add(*skills_to_add)
            del request.session[SESSION_KEY]
            added = [
                counted(
                    sum(1 for item in work if item.include), "position", "positions"
                ),
                counted(
                    sum(1 for item in education if item.include), "school", "schools"
                ),
                counted(
                    sum(1 for item in certifications if item.include),
                    "certification",
                    "certifications",
                ),
                counted(len(skills_to_add), "skill", "skills"),
            ]
            summary_note = (
                " and replaced your summary" if replace_summary and summary else ""
            )
            messages.success(
                request, f"Added {', '.join(added)} to your resume{summary_note}."
            )
            return redirect(reverse("tracker:resume"))
        messages.error(request, "Some entries need fixing before they can be added.")

    return render(
        request,
        "tracker/resume_import_review.html",
        {
            "warnings": extraction.warnings,
            "summary": summary,
            "replace_summary": replace_summary,
            "has_summary": bool(current.summary.strip()),
            "work": work,
            "education": education,
            "certifications": certifications,
            "skills": [
                {
                    "id": str(skill.id),
                    "name": skill.name,
                    "existing": str(skill.id) in existing_skill_ids,
                    "checked": str(skill.id) in chosen_skill_ids,
                }
                for skill in found_skills
            ],
        },
    )
