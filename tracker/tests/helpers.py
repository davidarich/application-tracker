"""Shared helpers for the tracker tests (not collected as tests itself)."""

import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from django.test import SimpleTestCase, override_settings

from accounts.models import User

from ..models import Application, ApplicationStatusChange, Company, Job

Status = Application.Status


TODAY = date(2026, 11, 24)


def at(day: date, hour: int = 12) -> datetime:
    """A UTC moment on `day` (the project's TIME_ZONE is UTC)."""
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def owner() -> User:
    """The user who owns the tests' default data (created on first use)."""
    return User.objects.get_or_create(email="owner@example.com")[0]


def make_job() -> Job:
    company = Company.objects.create(
        user_owner=owner(), name=f"Company {Company.objects.count()}"
    )
    return Job.objects.create(company=company, title="Engineer")


def make_application(created: datetime, status: str = Status.APPLIED) -> Application:
    """Create an application whose first history entry is dated `created`."""
    application = Application.objects.create(job=make_job(), status=status)
    _ = ApplicationStatusChange.objects.filter(application=application).update(
        changed_at=created
    )
    return application


def change_status(application: Application, status: str, when: datetime) -> None:
    application.status = status
    application.save()
    _ = ApplicationStatusChange.objects.filter(
        application=application, status=status
    ).update(changed_at=when)


def make_job_with_status(
    title: str, company: str, status: str | None, updated: datetime
) -> Job:
    """A job whose latest application (if any) has `status` and was last updated at `updated`."""
    job = Job.objects.create(
        company=Company.objects.get_or_create(user_owner=owner(), name=company)[0],
        title=title,
    )
    _ = Job.objects.filter(id=job.id).update(date_added=updated)
    if status is not None:
        application = Application.objects.create(job=job, status=status)
        _ = Application.objects.filter(id=application.id).update(updated_at=updated)
    return job


def current_jobs_view(page: str) -> list[str]:
    """The label(s) of the Jobs page view toggle marked as the current page."""
    start = page.index('aria-label="Jobs view"')
    group = page[start : page.index("</div>", start)]
    links = cast(list[str], re.findall(r"<a\b[^>]*>.*?</a>", group, re.DOTALL))
    return [
        re.sub(r"<[^>]+>", "", link).split()[-1]
        for link in links
        if 'aria-current="page"' in link
    ]


def temporary_media(test_class: type[SimpleTestCase]) -> Path:
    """Send `test_class`'s uploads to a temporary folder, not the real uploads/.

    Call from setUpClass, before super().setUpClass().
    """
    media = tempfile.TemporaryDirectory()
    test_class.addClassCleanup(media.cleanup)
    _ = test_class.enterClassContext(override_settings(MEDIA_ROOT=media.name))
    return Path(media.name)
