import uuid
from datetime import datetime
from pathlib import PurePath
from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Prefetch, Q
from django.db.models.functions import Lower
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.http import request_user, require_staff
from accounts.models import User

from .charts import build_status_chart, status_counts
from .forms import CompanyForm, ContactForm, SkillForm, make_job_form
from .jobs import (
    FINISHED_STATUSES,
    STATUS_ALL,
    STATUS_FILTER_OPTIONS,
    JobFilters,
    StatusMove,
    company_options,
    job_list,
    kanban_columns,
    set_job_status,
    sort_columns,
    undo_status_move,
)
from .models import Application, Company, Contact, File, Job, Skill
from .ownership import (
    active_skills,
    companies_for,
    contacts_for,
    deleted_companies_for,
    deleted_jobs_for,
    deleted_skills,
    files_for,
    jobs_for,
    status_changes_for,
)
from .paging import paging_context, parse_per_page
from .resume_views import deleted_entries, restore_entry, section_for_undo
from .status import STATUS_ORDER, status_label
from .undo import UNDO_SESSION_KEY, offer_undo


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    user = request_user(request)
    chart = build_status_chart(status_counts(user))
    return render(
        request,
        "tracker/dashboard.html",
        {"chart": chart, "chart_data": chart.to_json()},
    )


@login_required
def jobs(request: HttpRequest) -> HttpResponse:
    """The user's jobs, as a filterable, sortable, paged table (see
    tracker/jobs.py); with ?view=list, the same jobs as large cards with their
    skills and description; or, with ?view=kanban, a board with a column per
    open status."""
    user = request_user(request)
    filters = JobFilters.from_query(request.GET)
    context: dict[str, object] = {
        "filters": filters,
        "has_jobs": jobs_for(user).exists(),
        "status_options": STATUS_FILTER_OPTIONS,
        "companies": company_options(user),
    }
    if request.GET.get("view") == "kanban":
        context |= {
            "kanban": True,
            "columns": kanban_columns(user, filters),
            "card_statuses": [(str(s.value), str(s.label)) for s in STATUS_ORDER],
        }
    else:
        list_view = request.GET.get("view") == "list"
        job_rows = job_list(user, filters)
        if list_view:
            # The cards show each job's (active) skills, alphabetically.
            job_rows = job_rows.prefetch_related(
                Prefetch("skills", queryset=active_skills().order_by(Lower("name")))
            )
        # get_page() falls back to the first page for a bad number and to the
        # last page for one past the end, so a stale link never errors.
        page = Paginator(job_rows, filters.per_page).get_page(request.GET.get("page"))
        context |= {
            **paging_context(page, filters.per_page, anchor="jobs"),
            "columns": sort_columns(filters),
            "list_view": list_view,
        }
    return render(request, "tracker/jobs.html", context)


@login_required
@require_POST
def job_status(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Change one of the user's jobs' status (from the jobs board)."""
    job = get_object_or_404(jobs_for(request_user(request)), pk=pk)
    status = request.POST.get("status", "")
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = f"{reverse('tracker:jobs')}?view=kanban"
    next_url = next_url.split("#")[0]
    if status and status not in Application.Status.values:
        messages.error(request, "Choose one of the listed statuses.")
    elif status and (move := set_job_status(job, status)):
        label = status_label(status)
        text = f"Moved {job.title} to {label}."
        if status in FINISHED_STATUSES:
            text += f" {label} jobs aren't shown on the board."
        offer_status_undo(request, job, move, next_url, text)
    # Back to where the change was made, scrolled to the job's card.
    return redirect(f"{next_url}#job-{job.id}")


@login_required
def job_add(request: HttpRequest) -> HttpResponse:
    """Let the user add a job at one of their companies."""
    user = request_user(request)
    form = make_job_form(request.POST or None, user)
    if request.method == "POST" and form.is_valid():
        job = cast(Job, form.save())
        messages.success(request, f"Added {job.title} at {job.company.name}.")
        return redirect("tracker:jobs")
    return render(
        request,
        "tracker/job_form.html",
        {
            "form": form,
            "has_companies": companies_for(user).exists(),
            "heading": "Add job",
            "submit_label": "Add job",
            "action": reverse("tracker:job_add"),
        },
    )


@login_required
def job_detail(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """One of the user's jobs, with its skills and status history; anyone
    else's is a 404."""
    user = request_user(request)
    job = get_object_or_404(
        job_list(user, JobFilters(status=STATUS_ALL)).select_related("company"),
        pk=pk,
    )
    return render(
        request,
        "tracker/job_detail.html",
        {
            "job": job,
            "skills": job.skills.filter(is_deleted=False).order_by(Lower("name")),
            "history": status_changes_for(user)
            .filter(application__job=job)
            .order_by("-changed_at"),
        },
    )


@login_required
def job_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Let the user edit one of their jobs; anyone else's is a 404."""
    user = request_user(request)
    job = get_object_or_404(jobs_for(user).select_related("company"), pk=pk)
    original_title = job.title
    form = make_job_form(request.POST or None, user, job)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved {job.title} at {job.company.name}.")
        return redirect("tracker:job_detail", pk=job.id)
    return render(
        request,
        "tracker/job_form.html",
        {
            "form": form,
            "has_companies": True,
            "job_title": original_title,
            "job_url": reverse("tracker:job_detail", args=[job.id]),
            "heading": f"Edit {original_title}",
            "submit_label": "Save changes",
            "action": reverse("tracker:job_edit", args=[job.id]),
            "delete_action": reverse("tracker:job_delete", args=[job.id]),
        },
    )


@login_required
def download_file(request: HttpRequest, name: str) -> FileResponse:
    """Serve an uploaded file to its owner (or a superuser, e.g. from the admin).

    Anyone else gets a 404, as if the file didn't exist. Files are always sent
    as downloads, so an uploaded HTML or SVG file can't run in the site's pages.
    """
    user = request_user(request)
    files = File.objects.all() if user.is_superuser else files_for(user)
    file = get_object_or_404(files, path=name)
    extension = PurePath(file.path.name).suffix
    filename = (
        file.name
        if file.name.lower().endswith(extension)
        else f"{file.name}{extension}"
    )
    try:
        handle = file.path.open("rb")
    except FileNotFoundError:
        raise Http404("The file is missing from storage.") from None
    return FileResponse(handle, as_attachment=True, filename=filename)


@login_required
def companies(request: HttpRequest) -> HttpResponse:
    """The user's companies, with how many jobs each has.

    The q parameter searches company names and websites, ignoring case.
    """
    user = request_user(request)
    query = request.GET.get("q", "").strip()[:200]
    company_list = companies_for(user).annotate(
        job_count=Count("jobs", filter=Q(jobs__is_deleted=False))
    )
    if query:
        company_list = company_list.filter(
            Q(name__icontains=query) | Q(website__icontains=query)
        )
    company_list = company_list.order_by("name", "id")
    per_page = parse_per_page(request.GET)
    # get_page() falls back to the first page for a bad number and to the last
    # page for one past the end, so a stale link never errors.
    page = Paginator(company_list, per_page).get_page(request.GET.get("page"))
    return render(
        request,
        "tracker/companies.html",
        {
            "companies": page,
            "query": query,
            "total_companies": companies_for(user).count(),
            **paging_context(page, per_page, anchor="companies"),
        },
    )


@login_required
def company_add(request: HttpRequest) -> HttpResponse:
    """Let the user add a company of their own."""
    user = request_user(request)
    form = CompanyForm(request.POST or None, instance=Company(user_owner=user))
    if request.method == "POST" and save_company_form(form, user):
        company = cast(Company, form.instance)
        messages.success(request, f"Added {company.name}.")
        return redirect("tracker:companies")
    return render(
        request,
        "tracker/company_form.html",
        {
            "form": form,
            "heading": "Add company",
            "submit_label": "Add company",
            "action": reverse("tracker:company_add"),
        },
    )


@login_required
def company_detail(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """One of the user's companies, with its contacts and all its jobs; anyone
    else's is a 404."""
    user = request_user(request)
    company = get_object_or_404(companies_for(user), pk=pk)
    company_jobs = job_list(user, JobFilters(status=STATUS_ALL, company=company.id))
    return render(
        request,
        "tracker/company_detail.html",
        {
            "company": company,
            "contacts": contacts_for(user).filter(company=company).order_by("name"),
            "company_jobs": company_jobs,
        },
    )


def contacts_url(company: Company) -> str:
    """The Contacts section of a company's page."""
    return f"{reverse('tracker:company_detail', args=[company.id])}#contacts"


def contact_form_page(
    request: HttpRequest, company: Company, contact: Contact | None
) -> HttpResponse:
    """Add a contact to `company` (contact is None) or edit `contact`."""
    form = ContactForm(request.POST or None, instance=contact)
    if request.method == "POST" and form.is_valid():
        saved = cast(Contact, form.save(commit=False))
        saved.company = company
        saved.save()
        messages.success(request, f"Saved {saved.name}.")
        return redirect(contacts_url(company))
    context: dict[str, object] = {
        "form": form,
        "company": company,
        "company_url": contacts_url(company),
    }
    if contact is None:
        context |= {
            "heading": f"Add a contact at {company.name}",
            "submit_label": "Add contact",
            "action": reverse("tracker:contact_add", args=[company.id]),
        }
    else:
        context |= {
            "heading": f"Edit {contact.name}",
            "contact_name": contact.name,
            "submit_label": "Save changes",
            "action": reverse("tracker:contact_edit", args=[contact.id]),
            "delete_action": reverse("tracker:contact_delete", args=[contact.id]),
        }
    return render(request, "tracker/contact_form.html", context)


@login_required
def contact_add(request: HttpRequest, company_pk: uuid.UUID) -> HttpResponse:
    """Add a contact to one of the user's companies; anyone else's is a 404."""
    company = get_object_or_404(companies_for(request_user(request)), pk=company_pk)
    return contact_form_page(request, company, None)


@login_required
def contact_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Edit a contact at one of the user's companies; anyone else's is a 404."""
    user = request_user(request)
    contact = get_object_or_404(contacts_for(user).select_related("company"), pk=pk)
    return contact_form_page(request, contact.company, contact)


@login_required
@require_POST
def contact_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Delete a contact, for good (contacts aren't soft deleted)."""
    user = request_user(request)
    contact = get_object_or_404(contacts_for(user).select_related("company"), pk=pk)
    company, name = contact.company, contact.name
    _ = contact.delete()
    messages.success(request, f"Deleted {name}.")
    return redirect(contacts_url(company))


@login_required
def company_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Let the user edit one of their companies; anyone else's is a 404."""
    user = request_user(request)
    company = get_object_or_404(companies_for(user), pk=pk)
    original_name = company.name
    form = CompanyForm(request.POST or None, instance=company)
    if request.method == "POST" and save_company_form(form, user):
        messages.success(request, f"Saved {company.name}.")
        return redirect("tracker:company_detail", pk=company.id)
    return render(
        request,
        "tracker/company_form.html",
        {
            "form": form,
            "company_name": original_name,
            "company_url": reverse("tracker:company_detail", args=[company.id]),
            "heading": f"Edit {original_name}",
            "submit_label": "Save changes",
            "action": reverse("tracker:company_edit", args=[company.id]),
            "delete_action": reverse("tracker:company_delete", args=[company.id]),
        },
    )


def save_company_form(form: CompanyForm, user: User) -> bool:
    """Validate and save a bound company form; return whether it was saved.

    Duplicate names are checked here because the owner isn't a form field, so
    the model form's validation skips the per-user unique name constraint. The
    check runs whenever the name itself is valid, so all errors show at once,
    and ignores the company being edited.
    """
    is_valid = form.is_valid()
    name = cast(str, form.cleaned_data.get("name", ""))
    company = cast(Company, form.instance)
    duplicates = companies_for(user).filter(name__iexact=name).exclude(id=company.id)
    if name and duplicates.exists():
        form.add_error("name", "You already have a company with this name.")
        is_valid = False
    if is_valid:
        form.save()
    return is_valid


@login_required
def skills(request: HttpRequest) -> HttpResponse:
    """The shared skills (staff only). The q parameter searches names and descriptions."""
    _ = require_staff(request)
    query = request.GET.get("q", "").strip()[:200]
    skill_list = active_skills()
    if query:
        skill_list = skill_list.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    # Ignoring case, so "Amazon S3" sorts before "AWS Lambda".
    skill_list = skill_list.order_by(Lower("name"), "id")
    per_page = parse_per_page(request.GET)
    # get_page() falls back to the first page for a bad number and to the last
    # page for one past the end, so a stale link never errors.
    page = Paginator(skill_list, per_page).get_page(request.GET.get("page"))
    return render(
        request,
        "tracker/skills.html",
        {
            "skills": page,
            "query": query,
            "total_skills": active_skills().count(),
            **paging_context(page, per_page, anchor="skills"),
        },
    )


@login_required
def skill_add(request: HttpRequest) -> HttpResponse:
    """Add a shared skill (staff only)."""
    _ = require_staff(request)
    form = SkillForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        skill = cast(Skill, form.save())
        messages.success(request, f"Added {skill.name}.")
        return redirect("tracker:skills")
    return render(
        request,
        "tracker/skill_form.html",
        {
            "form": form,
            "heading": "Add skill",
            "submit_label": "Add skill",
            "action": reverse("tracker:skill_add"),
        },
    )


@login_required
def skill_edit(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Edit a shared skill (staff only)."""
    _ = require_staff(request)
    skill = get_object_or_404(active_skills(), pk=pk)
    original_name = skill.name
    form = SkillForm(request.POST or None, instance=skill)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved {skill.name}.")
        return redirect("tracker:skills")
    return render(
        request,
        "tracker/skill_form.html",
        {
            "form": form,
            "skill_name": original_name,
            "heading": f"Edit {original_name}",
            "submit_label": "Save changes",
            "action": reverse("tracker:skill_edit", args=[skill.id]),
            "delete_action": reverse("tracker:skill_delete", args=[skill.id]),
        },
    )


# Soft deletes: the record is only marked is_deleted, which hides it (and, for a
# company, its jobs, contacts and applications) everywhere in the app. It stays
# in the database and can be restored in the admin.


@login_required
@require_POST
def company_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Soft-delete one of the user's companies; anyone else's is a 404."""
    company = get_object_or_404(companies_for(request_user(request)), pk=pk)
    company.is_deleted, company.deleted_at = True, timezone.now()
    company.save(update_fields=["is_deleted", "deleted_at"])
    offer_undo(request, "company", company.id, company.name)
    return redirect("tracker:companies")


@login_required
@require_POST
def job_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Soft-delete one of the user's jobs; anyone else's is a 404."""
    job = get_object_or_404(jobs_for(request_user(request)), pk=pk)
    job.is_deleted, job.deleted_at = True, timezone.now()
    job.save(update_fields=["is_deleted", "deleted_at"])
    offer_undo(request, "job", job.id, job.title)
    return redirect("tracker:jobs")


@login_required
@require_POST
def skill_delete(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Soft-delete a shared skill (staff only)."""
    _ = require_staff(request)
    skill = get_object_or_404(active_skills(), pk=pk)
    skill.is_deleted, skill.deleted_at = True, timezone.now()
    skill.save(update_fields=["is_deleted", "deleted_at"])
    offer_undo(request, "skill", skill.id, skill.name)
    return redirect("tracker:skills")


# Undo: the last soft delete is remembered in the session, and its "Deleted …"
# message offers an Undo button (see layouts/app.html). Undo restores the
# record, re-checking it belongs to the user, and is used up once done.

UNDO_LISTS = {
    "company": "tracker:companies",
    "job": "tracker:jobs",
    "skill": "tracker:skills",
}


@login_required
@require_POST
def undo_delete(request: HttpRequest) -> HttpResponse:
    """Restore the user's last soft-deleted record."""
    user = request_user(request)
    undo = cast(dict[str, str] | None, request.session.pop(UNDO_SESSION_KEY, None))
    kind = undo.get("kind", "") if undo else ""
    resume_section = section_for_undo(kind)
    if undo is None or (kind not in UNDO_LISTS and resume_section is None):
        messages.error(request, "There's nothing to undo.")
        return redirect("tracker:dashboard")
    label = undo.get("label", "")
    try:
        record_id = uuid.UUID(undo.get("id", ""))
    except ValueError:
        messages.error(request, "There's nothing to undo.")
        return redirect("tracker:dashboard")

    error: str | None
    if resume_section is not None:
        error = restore_entry(user, resume_section, record_id)
    elif kind == "company":
        error = restore_company(user, record_id)
    elif kind == "job":
        error = restore_job(user, record_id)
    else:
        _ = require_staff(request)
        error = restore_skill(record_id)

    if error:
        messages.error(request, f"Couldn't restore {label}: {error}")
    else:
        messages.success(request, f"Restored {label}.")
    if resume_section is not None:
        return redirect(resume_section.url())
    return redirect(UNDO_LISTS[kind])


def restore_company(user: User, record_id: uuid.UUID) -> str | None:
    """Undelete one of the user's companies; return why not, if it can't be."""
    company = deleted_companies_for(user).filter(id=record_id).first()
    if company is None:
        return "it's no longer deleted, or doesn't exist."
    if companies_for(user).filter(name__iexact=company.name).exists():
        return "you've since added a company with the same name."
    company.is_deleted, company.deleted_at = False, None
    company.save(update_fields=["is_deleted", "deleted_at"])
    return None


def restore_job(user: User, record_id: uuid.UUID) -> str | None:
    """Undelete one of the user's jobs; return why not, if it can't be."""
    job = deleted_jobs_for(user).filter(id=record_id).first()
    if job is None:
        return "it's no longer deleted, or doesn't exist."
    job.is_deleted, job.deleted_at = False, None
    job.save(update_fields=["is_deleted", "deleted_at"])
    return None


def restore_skill(record_id: uuid.UUID) -> str | None:
    """Undelete a shared skill; return why not, if it can't be."""
    skill = deleted_skills().filter(id=record_id).first()
    if skill is None:
        return "it's no longer deleted, or doesn't exist."
    if active_skills().filter(name__iexact=skill.name).exists():
        return "a skill with the same name has since been added."
    skill.is_deleted, skill.deleted_at = False, None
    skill.save(update_fields=["is_deleted", "deleted_at"])
    return None


# Recently deleted: the user's soft-deleted companies, jobs and resume entries,
# newest first, each with a Restore button.

RECENTLY_DELETED_LIMIT = 100


@login_required
def recently_deleted(request: HttpRequest) -> HttpResponse:
    user = request_user(request)
    newest_first = (F("deleted_at").desc(nulls_last=True), F("id").asc())
    companies = (
        deleted_companies_for(user)
        .annotate(job_count=Count("jobs", filter=Q(jobs__is_deleted=False)))
        .order_by(*newest_first)
    )
    jobs = deleted_jobs_for(user).select_related("company").order_by(*newest_first)
    resume_entries = deleted_entries(user)
    return render(
        request,
        "tracker/recently_deleted.html",
        {
            "companies": companies[:RECENTLY_DELETED_LIMIT],
            "company_count": companies.count(),
            "jobs": jobs[:RECENTLY_DELETED_LIMIT],
            "job_count": jobs.count(),
            "resume_entries": resume_entries[:RECENTLY_DELETED_LIMIT],
            "resume_entry_count": len(resume_entries),
            "limit": RECENTLY_DELETED_LIMIT,
        },
    )


@login_required
@require_POST
def company_restore(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Restore one of the user's deleted companies (with its jobs)."""
    user = request_user(request)
    company = get_object_or_404(deleted_companies_for(user), pk=pk)
    error = restore_company(user, company.id)
    if error:
        messages.error(request, f"Couldn't restore {company.name}: {error}")
    else:
        messages.success(request, f"Restored {company.name}.")
    return redirect("tracker:recently_deleted")


@login_required
@require_POST
def job_restore(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Restore one of the user's deleted jobs."""
    user = request_user(request)
    job = get_object_or_404(deleted_jobs_for(user).select_related("company"), pk=pk)
    error = restore_job(user, job.id)
    if error:
        messages.error(request, f"Couldn't restore {job.title}: {error}")
    elif job.company.is_deleted:
        messages.success(
            request,
            f"Restored {job.title}, but it stays hidden until you restore "
            + f"its company, {job.company.name}.",
        )
    else:
        messages.success(request, f"Restored {job.title}.")
    return redirect("tracker:recently_deleted")


# Admin Recently deleted: soft-deleted records of the shared, staff-managed
# models (not owned by any user), one table per model, with Restore buttons.
# Skills are the only such model so far; add a section here (and in the
# template) for each new one.


@login_required
def admin_recently_deleted(request: HttpRequest) -> HttpResponse:
    """Deleted shared records, newest first, by model (staff only)."""
    _ = require_staff(request)
    newest_first = (F("deleted_at").desc(nulls_last=True), F("id").asc())
    skills = deleted_skills().order_by(*newest_first)
    return render(
        request,
        "tracker/admin_recently_deleted.html",
        {
            "skills": skills[:RECENTLY_DELETED_LIMIT],
            "skill_count": skills.count(),
            "limit": RECENTLY_DELETED_LIMIT,
        },
    )


@login_required
@require_POST
def skill_restore(request: HttpRequest, pk: uuid.UUID) -> HttpResponse:
    """Restore a deleted shared skill (staff only)."""
    _ = require_staff(request)
    skill = get_object_or_404(deleted_skills(), pk=pk)
    error = restore_skill(skill.id)
    if error:
        messages.error(request, f"Couldn't restore {skill.name}: {error}")
    else:
        messages.success(request, f"Restored {skill.name}.")
    return redirect("tracker:admin_recently_deleted")


# Undo for status moves: the last move is remembered in the session, and its
# "Moved …" message offers an Undo button (see layouts/app.html).

UNDO_STATUS_SESSION_KEY = "undo_status"


def offer_status_undo(
    request: HttpRequest, job: Job, move: StatusMove, next_url: str, text: str
) -> None:
    """Remember a status move for undo, and say it happened (with an Undo button)."""
    token = uuid.uuid4().hex
    request.session[UNDO_STATUS_SESSION_KEY] = {
        "token": token,
        "job_id": str(job.id),
        "title": job.title,
        "next": next_url,
        "application_id": str(move.application_id),
        "status": move.status,
        "created": move.created,
        "previous_status": move.previous_status,
        "previous_updated_at": (
            move.previous_updated_at.isoformat() if move.previous_updated_at else None
        ),
        "change_id": str(move.change_id) if move.change_id else None,
    }
    # The token in the tags ties this message's Undo button to this move.
    messages.success(request, text, extra_tags=f"undo-status undo-{token}")


@login_required
@require_POST
def undo_status(request: HttpRequest) -> HttpResponse:
    """Put back the user's last job status move."""
    user = request_user(request)
    undo = cast(
        dict[str, object] | None, request.session.pop(UNDO_STATUS_SESSION_KEY, None)
    )
    board = f"{reverse('tracker:jobs')}?view=kanban"
    try:
        assert undo is not None
        previous_updated_at = cast(str | None, undo["previous_updated_at"])
        change_id = cast(str | None, undo["change_id"])
        move = StatusMove(
            application_id=uuid.UUID(cast(str, undo["application_id"])),
            status=cast(str, undo["status"]),
            created=bool(undo["created"]),
            previous_status=cast(str | None, undo["previous_status"]),
            previous_updated_at=(
                datetime.fromisoformat(previous_updated_at)
                if previous_updated_at
                else None
            ),
            change_id=uuid.UUID(change_id) if change_id else None,
        )
        title, job_id = cast(str, undo["title"]), cast(str, undo["job_id"])
        next_url = cast(str, undo["next"])
    except (AssertionError, KeyError, ValueError, TypeError):
        messages.error(request, "There's nothing to undo.")
        return redirect(board)

    error = undo_status_move(user, move)
    if error:
        messages.error(request, f"Couldn't undo the move of {title}: {error}")
    else:
        messages.success(
            request, f"Moved {title} back to {status_label(move.previous_status)}."
        )
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = board
    return redirect(f"{next_url}#job-{job_id}")
