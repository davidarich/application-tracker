"""Filtering and sorting the job list."""

from datetime import timedelta
from typing import ClassVar, override

from django.http import QueryDict
from django.test import TestCase

from ..jobs import JobFilters, job_list, sort_columns
from ..models import Application, Company, Job
from ..status import status_label, status_slot
from .helpers import (
    TODAY,
    Status,
    at,
    make_job_with_status,
    owner,
)


class JobFiltersTests(TestCase):
    def test_defaults(self):
        filters = JobFilters.from_query(QueryDict(""))
        self.assertEqual(filters, JobFilters(query="", status="open", sort="-updated"))
        self.assertFalse(filters.is_filtered)

    def test_reads_valid_values(self):
        company = Company.objects.create(user_owner=owner(), name="Acme")
        filters = JobFilters.from_query(
            QueryDict(f"q=+dev+&status=offer&company={company.id}&sort=title")
        )
        self.assertEqual(filters.query, "dev")
        self.assertEqual(filters.status, "offer")
        self.assertEqual(filters.company, company.id)
        self.assertEqual(filters.sort, "title")
        self.assertTrue(filters.is_filtered)

    def test_invalid_values_fall_back_to_defaults(self):
        filters = JobFilters.from_query(
            QueryDict("status=bogus&company=not-a-uuid&sort=-password")
        )
        self.assertEqual(filters, JobFilters())

    def test_sorting_alone_is_not_filtering(self):
        self.assertFalse(JobFilters.from_query(QueryDict("sort=title")).is_filtered)


class JobListTests(TestCase):
    closed: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        base = at(TODAY - timedelta(days=10))
        _ = make_job_with_status("Backend", "Acme", Status.APPLIED, base)
        _ = make_job_with_status(
            "Frontend", "Globex", Status.OFFER, base + timedelta(days=3)
        )
        cls.closed = make_job_with_status(
            "Data", "Acme", Status.CLOSED, base + timedelta(days=5)
        )
        _ = make_job_with_status("Mobile", "Initech", None, base + timedelta(days=1))

    def titles(self, **filters: str) -> list[str]:
        return [
            job.title
            for job in job_list(owner(), JobFilters.from_query(self.query(filters)))
        ]

    def query(self, filters: dict[str, str]) -> QueryDict:
        params = QueryDict(mutable=True)
        params.update(filters)
        return params

    def test_default_hides_closed_and_sorts_by_most_recently_updated(self):
        self.assertEqual(self.titles(), ["Frontend", "Mobile", "Backend"])

    def test_all_statuses_includes_closed(self):
        self.assertEqual(
            self.titles(status="all"), ["Data", "Frontend", "Mobile", "Backend"]
        )

    def test_filter_by_status(self):
        self.assertEqual(self.titles(status="closed"), ["Data"])
        self.assertEqual(self.titles(status="none"), ["Mobile"])

    def test_filter_by_company(self):
        acme = Company.objects.get(name="Acme")
        self.assertEqual(
            self.titles(status="all", company=str(acme.id)), ["Data", "Backend"]
        )

    def test_search_matches_title_or_company(self):
        self.assertEqual(self.titles(q="front"), ["Frontend"])
        self.assertEqual(self.titles(q="initech"), ["Mobile"])

    def test_sort_by_title_both_ways(self):
        self.assertEqual(self.titles(sort="title"), ["Backend", "Frontend", "Mobile"])
        self.assertEqual(self.titles(sort="-title"), ["Mobile", "Frontend", "Backend"])

    def test_sort_by_status_follows_the_pipeline(self):
        self.assertEqual(
            self.titles(status="all", sort="status"),
            ["Mobile", "Backend", "Frontend", "Data"],
        )

    def test_uses_the_latest_application(self):
        application = Application.objects.create(
            job=self.closed, status=Status.RESPONDED
        )
        _ = Application.objects.filter(id=application.id).update(updated_at=at(TODAY))
        job = job_list(owner(), JobFilters()).first()
        assert job is not None
        self.assertEqual(job.title, "Data")


class SortColumnsTests(TestCase):
    def test_active_column_flips_and_others_use_their_first_direction(self):
        columns = {c.name: c for c in sort_columns(JobFilters(sort="-updated"))}
        self.assertEqual(columns["updated"].direction, "descending")
        self.assertEqual(columns["updated"].next_sort, "updated")
        self.assertEqual(columns["title"].next_sort, "title")
        self.assertIsNone(columns["title"].direction)

        columns = {c.name: c for c in sort_columns(JobFilters(sort="title"))}
        self.assertEqual(columns["title"].direction, "ascending")
        self.assertEqual(columns["title"].next_sort, "-title")
        self.assertEqual(columns["updated"].next_sort, "-updated")


class SecondarySortTests(TestCase):
    """Ties in the primary sort fall back to updated, then status, then title."""

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        same_time = at(TODAY - timedelta(days=2))
        # Four jobs updated at the same moment, in no particular status order.
        _ = make_job_with_status("Delta", "Acme", Status.OFFER, same_time)
        _ = make_job_with_status("Alpha", "Acme", Status.CLOSED, same_time)
        _ = make_job_with_status("Charlie", "Globex", Status.APPLIED, same_time)
        _ = make_job_with_status("Bravo", "Globex", None, same_time)
        _ = make_job_with_status("Echo", "Acme", Status.APPLIED, same_time)
        # Updated later, so it leads the default sort whatever its status.
        _ = make_job_with_status("Foxtrot", "Initech", Status.CLOSED, at(TODAY))

    def titles(self, **params: str) -> list[str]:
        query = QueryDict(mutable=True)
        query.update({"status": "all", **params})
        return [job.title for job in job_list(owner(), JobFilters.from_query(query))]

    def test_default_sort_is_updated_then_status_then_title(self):
        self.assertEqual(
            self.titles(),
            # Newest first; then not applied, applied (Charlie, Echo by title),
            # offer, closed.
            ["Foxtrot", "Bravo", "Charlie", "Echo", "Delta", "Alpha"],
        )

    def test_sorting_by_status_breaks_ties_by_updated(self):
        self.assertEqual(
            self.titles(sort="status"),
            ["Bravo", "Charlie", "Echo", "Delta", "Foxtrot", "Alpha"],
        )

    def test_sorting_by_title_breaks_ties_by_updated_then_status(self):
        _ = make_job_with_status(
            "Alpha", "Globex", Status.APPLIED, at(TODAY - timedelta(days=2))
        )
        _ = make_job_with_status("Alpha", "Initech", Status.APPLIED, at(TODAY))
        filters = JobFilters.from_query(QueryDict("status=all&sort=title"))
        alpha_companies = [
            job.company.name
            for job in job_list(owner(), filters)
            if job.title == "Alpha"
        ]
        # Newest first (Initech); then, updated together, applied (Globex)
        # before closed (Acme).
        self.assertEqual(alpha_companies, ["Initech", "Globex", "Acme"])


class IgnoredJobFilterTests(TestCase):
    @classmethod
    @override
    def setUpTestData(cls) -> None:
        when = at(TODAY - timedelta(days=1))
        _ = make_job_with_status("Pursuing", "Acme", Status.APPLIED, when)
        _ = make_job_with_status("Skipped", "Globex", Status.IGNORED, when)
        _ = make_job_with_status("Finished", "Initech", Status.CLOSED, when)

    def titles(self, query: str) -> list[str]:
        return [
            job.title
            for job in job_list(owner(), JobFilters.from_query(QueryDict(query)))
        ]

    def test_default_open_filter_hides_ignored_and_closed_jobs(self):
        self.assertEqual(self.titles(""), ["Pursuing"])

    def test_ignored_filter_shows_only_ignored_jobs(self):
        self.assertEqual(self.titles("status=ignored"), ["Skipped"])

    def test_all_statuses_includes_ignored(self):
        self.assertEqual(
            sorted(self.titles("status=all")), ["Finished", "Pursuing", "Skipped"]
        )

    def test_ignored_has_its_own_status_colour(self):
        self.assertEqual(status_slot(Status.IGNORED), 6)
        self.assertEqual(status_label(Status.IGNORED), "Ignored")
