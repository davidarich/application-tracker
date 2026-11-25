"""The View job page."""

from datetime import timedelta
from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from ..models import Application, Company, Job, Skill
from .helpers import Status, make_job_with_status, owner


class JobDetailTests(TestCase):
    job: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.job = make_job_with_status("Backend Engineer", "Acme", None, timezone.now())
        _ = Job.objects.filter(id=cls.job.id).update(
            location_city="Austin",
            location_state="TX",
            workplace_type=Job.WorkplaceType.REMOTE,
            salary_min=120000,
            posting_url="https://example.com/jobs/1",
            description="Build APIs.",
        )
        cls.job.skills.set(
            [
                Skill.objects.create(name="Python"),
                Skill.objects.create(name="docker"),
                Skill.objects.create(name="Perl", is_deleted=True),
            ]
        )

    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def url(self, job: Job | None = None) -> str:
        return reverse("tracker:job_detail", args=[(job or self.job).id])

    def page(self) -> str:
        return self.client.get(self.url()).content.decode()

    def test_requires_login(self):
        self.client.logout()
        url = self.url()
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_shows_the_details_and_an_edit_button(self):
        page = self.page()
        self.assertIn("Backend Engineer", page)
        company = reverse("tracker:company_detail", args=[self.job.company.id])
        self.assertIn(f'href="{company}"', page)
        self.assertIn("Not applied", page)
        self.assertIn("Austin, TX", page)
        self.assertIn("Remote", page)
        self.assertIn("From 120,000", page)
        self.assertIn(
            'href="https://example.com/jobs/1" target="_blank" rel="noopener noreferrer"',
            page,
        )
        self.assertIn("Build APIs.", page)
        edit = reverse("tracker:job_edit", args=[self.job.id])
        self.assertIn("Edit job", page[page.index(f'href="{edit}"') :][:1200])
        self.assertIn('ring-white/6">', page)  # Jobs nav stays active

    def test_lists_active_skills_alphabetically(self):
        page = self.page()
        skills = page[page.index('aria-label="Skills for') :]
        self.assertLess(skills.index(">docker<"), skills.index(">Python<"))
        self.assertNotIn("Perl", page)

    def test_status_history_newest_first(self):
        self.assertIn("no status history", self.page())
        application = Application.objects.create(job=self.job, status=Status.APPLIED)
        application.status = Status.INTERVIEWING
        application.save()
        page = self.page()
        history = page[page.index('id="history-title"') :]
        self.assertLess(history.index("Interviewing"), history.index("Applied"))

    def test_finished_jobs_can_be_viewed(self):
        closed = make_job_with_status(
            "Old Job", "Acme", Status.CLOSED, timezone.now() - timedelta(days=9)
        )
        response = self.client.get(self.url(closed))
        self.assertContains(response, "Closed")

    def test_edit_page_breadcrumb_and_cancel_lead_back_to_the_view_page(self):
        page = self.client.get(
            reverse("tracker:job_edit", args=[self.job.id])
        ).content.decode()
        self.assertEqual(page.count(f'href="{self.url()}"'), 2)

    def test_other_users_and_deleted_jobs_are_404(self):
        bob = User.objects.create_user("bob@example.com", "x")
        theirs = Job.objects.create(
            company=Company.objects.create(user_owner=bob, name="Bob Co"),
            title="Theirs",
        )
        self.assertEqual(self.client.get(self.url(theirs)).status_code, 404)
        _ = Job.objects.filter(id=self.job.id).update(is_deleted=True)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
