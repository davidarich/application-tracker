"""Recording application status changes."""

from django.test import TestCase

from ..models import Application, ApplicationStatusChange
from .helpers import (
    Status,
    make_job,
)


class StatusHistoryTests(TestCase):
    def history(self, application: Application) -> list[str]:
        return list(
            ApplicationStatusChange.objects.filter(application=application)
            .order_by("changed_at")
            .values_list("status", flat=True)
        )

    def test_new_application_records_its_status(self):
        application = Application.objects.create(job=make_job())
        self.assertEqual(self.history(application), [Status.APPLIED])

    def test_status_change_is_recorded(self):
        application = Application.objects.create(job=make_job())
        application.status = Status.INTERVIEWING
        application.save()
        self.assertEqual(
            self.history(application), [Status.APPLIED, Status.INTERVIEWING]
        )

    def test_save_without_status_change_records_nothing(self):
        application = Application.objects.create(job=make_job())
        application.save()
        application.save(update_fields=["updated_at"])
        self.assertEqual(self.history(application), [Status.APPLIED])

    def test_status_change_with_update_fields_is_recorded(self):
        application = Application.objects.create(job=make_job())
        application.status = Status.OFFER
        application.save(update_fields=["status"])
        self.assertEqual(self.history(application), [Status.APPLIED, Status.OFFER])
