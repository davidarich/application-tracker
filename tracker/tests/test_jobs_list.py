"""The Jobs page's list view: large cards with details, skills and a collapsible description."""

from collections.abc import Sequence
from typing import ClassVar, cast, override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from ..models import Job, Skill
from .helpers import Status, current_jobs_view, make_job_with_status, owner

LIST = f"{reverse('tracker:jobs')}?view=list"


class JobListViewTests(TestCase):
    job: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.job = make_job_with_status(
            "Backend Engineer", "Acme", Status.INTERVIEWING, timezone.now()
        )
        _ = Job.objects.filter(id=cls.job.id).update(
            location_city="Austin",
            location_state="TX",
            workplace_type=Job.WorkplaceType.HYBRID,
            salary_min=120000,
            salary_max=150000,
            posting_url="https://example.com/jobs/1",
            description="Build APIs.\nWork with the data team.",
        )
        python = Skill.objects.create(name="Python")
        docker = Skill.objects.create(name="docker")
        perl = Skill.objects.create(name="Perl", is_deleted=True)
        cls.job.skills.set([python, docker, perl])
        _ = make_job_with_status(
            "Data Engineer", "Globex", Status.CLOSED, timezone.now()
        )

    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def page(self, **params: str) -> str:
        return self.client.get(
            reverse("tracker:jobs"), {"view": "list", **params}
        ).content.decode()

    def card(self, page: str) -> str:
        start = page.index(f'id="job-{self.job.id}"')
        return page[start : page.index("</article>", start)]

    def test_toggle_marks_list_as_current(self):
        page = self.page()
        self.assertEqual(current_jobs_view(page), ["List"])
        table = self.client.get(reverse("tracker:jobs")).content.decode()
        self.assertIn("view=list", table)

    def test_card_shows_the_job_details(self):
        card = self.card(self.page())
        self.assertIn(reverse("tracker:job_detail", args=[self.job.id]), card)
        self.assertIn("Backend Engineer", card)
        self.assertIn("Acme", card)
        self.assertIn("Interviewing", card)
        self.assertIn("Austin, TX", card)
        self.assertIn("Hybrid", card)
        self.assertIn("120,000 – 150,000", card)
        self.assertIn(
            'href="https://example.com/jobs/1" target="_blank" rel="noopener noreferrer"',
            card,
        )

    def test_card_lists_active_skills_alphabetically(self):
        card = self.card(self.page())
        skills = card[card.index('aria-label="Skills for') :]
        self.assertLess(skills.index(">docker<"), skills.index(">Python<"))
        self.assertNotIn("Perl", card)

    def test_description_is_behind_a_collapsed_toggle(self):
        card = self.card(self.page())
        details = card[card.index("<details") :]
        self.assertNotIn("<details open", card)
        summary = details[details.index("<summary") : details.index("</summary>")]
        self.assertIn("Job Description", summary)
        self.assertIn("group-open:rotate-180", summary)  # the arrow flips when open
        self.assertIn("Build APIs.\nWork with the data team.", details)

    def test_missing_details_have_fallbacks(self):
        bare = make_job_with_status("Bare Job", "Initech", None, timezone.now())
        page = self.page()
        start = page.index(f'id="job-{bare.id}"')
        card = page[start : page.index("</article>", start)]
        self.assertIn("Not listed", card)
        self.assertIn("Not specified", card)
        self.assertIn("None listed", card)
        self.assertIn("No description.", card)
        self.assertIn("Not applied", card)

    def test_same_filters_as_the_table_and_they_keep_the_list_view(self):
        response = self.client.get(reverse("tracker:jobs"), {"view": "list"})
        titles = [job.title for job in cast(Sequence[Job], response.context["page"])]
        self.assertEqual(titles, ["Backend Engineer"])  # closed hidden by default
        page = self.page(status="all")
        self.assertIn("Data Engineer", page)
        self.assertIn('name="view" value="list"', page)
        self.assertIn('id="job-status"', page)  # unlike the board, status filters apply

    def test_paging_keeps_the_list_view(self):
        for n in range(30):
            _ = make_job_with_status(
                f"Job {n:02}", "Acme", Status.APPLIED, timezone.now()
            )
        page = self.page()
        self.assertIn("Showing 1–25 of 31", page)
        self.assertIn("view=list", page[page.index("Showing 1–25") :])

    def test_no_matches_and_no_jobs(self):
        self.assertIn("No jobs match these filters", self.page(q="zzz"))
        self.client.force_login(User.objects.create_user("new@example.com", "x"))
        self.assertIn("No jobs yet", self.page())

    def test_view_toggle_links_open_at_the_top_of_the_page(self):
        for url in (
            reverse("tracker:jobs"),
            LIST,
            f"{reverse('tracker:jobs')}?view=kanban",
        ):
            page = self.client.get(url).content.decode()
            start = page.index('aria-label="Jobs view"')
            group = page[start : page.index("</div>", start)]
            self.assertEqual(group.count("<a "), 3)
            self.assertNotIn("#", group)  # no anchor, so no jump down the page
