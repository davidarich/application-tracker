from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from accounts.forms import EmailAuthenticationForm

from . import resume_import_views, resume_views, views

app_name = "tracker"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="tracker:dashboard"), name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("jobs/", views.jobs, name="jobs"),
    path("jobs/new/", views.job_add, name="job_add"),
    path("jobs/<uuid:pk>/", views.job_detail, name="job_detail"),
    path("jobs/<uuid:pk>/edit/", views.job_edit, name="job_edit"),
    path("jobs/<uuid:pk>/delete/", views.job_delete, name="job_delete"),
    path("jobs/<uuid:pk>/status/", views.job_status, name="job_status"),
    path("companies/", views.companies, name="companies"),
    path("resume/", resume_views.resume, name="resume"),
    path("resume/import/", resume_import_views.resume_import, name="resume_import"),
    path("resume/file/", resume_views.resume_file, name="resume_file"),
    path(
        "resume/import/review/",
        resume_import_views.resume_import_review,
        name="resume_import_review",
    ),
    path(
        "resume/<slug:section>/new/",
        resume_views.resume_entry_add,
        name="resume_entry_add",
    ),
    path(
        "resume/<slug:section>/<uuid:pk>/edit/",
        resume_views.resume_entry_edit,
        name="resume_entry_edit",
    ),
    path(
        "resume/<slug:section>/<uuid:pk>/delete/",
        resume_views.resume_entry_delete,
        name="resume_entry_delete",
    ),
    path(
        "resume/<slug:section>/<uuid:pk>/restore/",
        resume_views.resume_entry_restore,
        name="resume_entry_restore",
    ),
    path("skills/", views.skills, name="skills"),
    path("skills/new/", views.skill_add, name="skill_add"),
    path("skills/<uuid:pk>/restore/", views.skill_restore, name="skill_restore"),
    path("skills/<uuid:pk>/edit/", views.skill_edit, name="skill_edit"),
    path("skills/<uuid:pk>/delete/", views.skill_delete, name="skill_delete"),
    path("undo-delete/", views.undo_delete, name="undo_delete"),
    path("undo-status/", views.undo_status, name="undo_status"),
    path("recently-deleted/", views.recently_deleted, name="recently_deleted"),
    # The Admin section's version, for shared staff-managed models. Not under
    # /admin/, which belongs to Django's admin site.
    path(
        "manage/recently-deleted/",
        views.admin_recently_deleted,
        name="admin_recently_deleted",
    ),
    path("companies/<uuid:pk>/restore/", views.company_restore, name="company_restore"),
    path("jobs/<uuid:pk>/restore/", views.job_restore, name="job_restore"),
    path("companies/new/", views.company_add, name="company_add"),
    path("companies/<uuid:pk>/", views.company_detail, name="company_detail"),
    path(
        "companies/<uuid:company_pk>/contacts/new/",
        views.contact_add,
        name="contact_add",
    ),
    path("contacts/<uuid:pk>/edit/", views.contact_edit, name="contact_edit"),
    path("contacts/<uuid:pk>/delete/", views.contact_delete, name="contact_delete"),
    path("companies/<uuid:pk>/edit/", views.company_edit, name="company_edit"),
    path("companies/<uuid:pk>/delete/", views.company_delete, name="company_delete"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            authentication_form=EmailAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
