"""The Jobs page: the job table, its filters, sorting and paging, and Add job."""

from collections.abc import Sequence
from typing import ClassVar, cast, override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from ..models import Company, Job, Skill
from .helpers import (
    Status,
    make_job_with_status,
    owner,
)


class JobsTableTests(TestCase):
    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def test_lists_open_jobs_by_default(self):
        _ = make_job_with_status("Backend", "Acme", Status.APPLIED, timezone.now())
        _ = make_job_with_status("Data", "Acme", Status.CLOSED, timezone.now())
        response = self.client.get(reverse("tracker:jobs"))
        self.assertContains(response, "Backend")
        self.assertNotContains(response, ">Data<")
        self.assertContains(response, 'aria-sort="descending"')
        self.assertContains(response, "1 job<")

    def test_filters_and_sort_come_from_the_query_string(self):
        _ = make_job_with_status("Data", "Acme", Status.CLOSED, timezone.now())
        response = self.client.get(
            reverse("tracker:jobs"), {"status": "closed", "sort": "title"}
        )
        self.assertContains(response, ">Data<")
        self.assertContains(response, 'aria-sort="ascending"')
        self.assertContains(response, "Reset")

    def test_no_match_message(self):
        _ = make_job_with_status("Backend", "Acme", Status.APPLIED, timezone.now())
        response = self.client.get(reverse("tracker:jobs"), {"q": "zzz"})
        self.assertContains(response, "No jobs match these filters")

    def test_empty_state_without_jobs(self):
        response = self.client.get(reverse("tracker:jobs"))
        self.assertContains(response, "No jobs yet")
        self.assertNotContains(response, "data-job-filters")


class JobsPagingTests(TestCase):
    @classmethod
    @override
    def setUpTestData(cls) -> None:
        company = Company.objects.create(user_owner=owner(), name="Acme")
        _ = Job.objects.bulk_create(
            Job(company=company, title=f"Job {n:03}") for n in range(105)
        )

    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def get(self, **params: str) -> list[str]:
        """Titles of the jobs on the dashboard page requested with `params`."""
        response = self.client.get(reverse("tracker:jobs"), params)
        # The context is untyped; "page" is a Paginator page, a sequence of jobs.
        page = cast(Sequence[Job], response.context["page"])
        return [job.title for job in page]

    def test_shows_25_per_page_by_default(self):
        self.assertEqual(len(self.get()), 25)
        response = self.client.get(reverse("tracker:jobs"))
        self.assertContains(response, "Showing 1–25 of 105")
        self.assertContains(response, "105 jobs")

    def test_last_page_has_the_rest(self):
        self.assertEqual(len(self.get(page="2")), 25)
        self.assertEqual(len(self.get(page="5")), 5)

    def test_bad_page_numbers_do_not_error(self):
        self.assertEqual(len(self.get(page="abc")), 25)  # falls back to page 1
        self.assertEqual(len(self.get(page="99")), 5)  # clamps to the last page

    def test_page_size_can_be_changed(self):
        self.assertEqual(len(self.get(per_page="100")), 100)

    def test_pages_follow_the_sort(self):
        self.assertEqual(self.get(sort="title", per_page="25", page="2")[0], "Job 025")

    def test_footer_says_no_results_when_a_filter_matches_nothing(self):
        response = self.client.get(reverse("tracker:jobs"), {"q": "zzz"})
        self.assertContains(response, "No jobs match these filters")
        self.assertContains(response, "No results")
        self.assertContains(response, "Per page")

    def test_page_links_keep_filters_and_sort_links_reset_the_page(self):
        response = self.client.get(
            reverse("tracker:jobs"), {"sort": "title", "page": "1"}
        )
        self.assertContains(response, "?sort=title&amp;page=2#jobs")
        self.assertContains(response, 'href="?sort=-title#jobs"')


class JobsPageTests(TestCase):
    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def test_requires_login(self):
        self.client.logout()
        url = reverse("tracker:jobs")
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_has_an_add_job_button_and_active_sidebar_link(self):
        page = self.client.get(reverse("tracker:jobs")).content.decode()
        self.assertIn(f'href="{reverse("tracker:job_add")}"', page)
        jobs_link = page[page.index(f'href="{reverse("tracker:jobs")}"') :][:400]
        self.assertIn('aria-current="page"', jobs_link)

    def test_empty_state_links_to_add_job(self):
        response = self.client.get(reverse("tracker:jobs"))
        self.assertContains(response, "No jobs yet")
        self.assertContains(response, "Add your first job")


class JobAddTests(TestCase):
    user: ClassVar[User]
    acme: ClassVar[Company]
    others: ClassVar[Company]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        other = User.objects.create_user("bob@example.com", "x")
        cls.others = Company.objects.create(user_owner=other, name="Globex")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def post(self, **fields: str) -> str:
        data = {"company": str(self.acme.id), "title": "Backend Engineer", **fields}
        response = self.client.post(reverse("tracker:job_add"), data, follow=True)
        return response.content.decode()

    def test_requires_login(self):
        self.client.logout()
        url = reverse("tracker:job_add")
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_company_choices_are_only_the_users_companies(self):
        page = self.client.get(reverse("tracker:job_add")).content.decode()
        self.assertIn(str(self.acme.id), page)
        self.assertNotIn(str(self.others.id), page)
        self.assertIn("Choose a company", page)

    def test_creates_a_job_and_returns_to_the_jobs_page(self):
        response = self.client.post(
            reverse("tracker:job_add"),
            {
                "company": str(self.acme.id),
                "title": "Backend Engineer",
                "location_city": "Austin",
                "location_state": "TX",
                "workplace_type": "hybrid",
                "salary_min": "120000",
                "salary_max": "150000",
                "description": "Build things.",
            },
            follow=True,
        )
        self.assertRedirects(response, reverse("tracker:jobs"))
        self.assertContains(response, "Added Backend Engineer at Acme.")
        job = Job.objects.get(title="Backend Engineer")
        self.assertEqual(job.company, self.acme)
        self.assertEqual(job.location, "Austin, TX")
        self.assertEqual(job.workplace_type, "hybrid")
        self.assertEqual((job.salary_min, job.salary_max), (120000, 150000))

    def test_only_company_and_title_are_required(self):
        _ = self.post()
        job = Job.objects.get()
        self.assertEqual(
            (job.workplace_type, job.salary_min, job.description), ("", None, "")
        )

    def test_rejects_another_users_company(self):
        page = self.post(company=str(self.others.id))
        self.assertIn("Select a valid choice", page)
        self.assertFalse(Job.objects.exists())

    def test_requires_company_and_title(self):
        page = self.post(company="", title="")
        self.assertEqual(page.count("This field is required."), 2)
        self.assertFalse(Job.objects.exists())

    def test_minimum_salary_cannot_exceed_maximum(self):
        page = self.post(salary_min="200000", salary_max="100000")
        self.assertIn("Minimum salary can&#x27;t exceed maximum salary.", page)
        self.assertFalse(Job.objects.exists())

    def test_asks_for_a_company_first_when_there_are_none(self):
        self.client.force_login(User.objects.create_user("new@example.com", "x"))
        response = self.client.get(reverse("tracker:job_add"))
        self.assertContains(response, "Add a company first")
        self.assertContains(response, f'href="{reverse("tracker:company_add")}"')
        self.assertNotContains(response, 'name="title"')


class JobEditTests(TestCase):
    user: ClassVar[User]
    acme: ClassVar[Company]
    globex: ClassVar[Company]
    job: ClassVar[Job]
    others_job: ClassVar[Job]
    others_company: ClassVar[Company]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        cls.globex = Company.objects.create(user_owner=cls.user, name="Globex")
        cls.job = Job.objects.create(
            company=cls.acme, title="Backend Engineer", location_city="Austin"
        )
        other = User.objects.create_user("bob@example.com", "x")
        cls.others_company = Company.objects.create(user_owner=other, name="Initech")
        cls.others_job = Job.objects.create(company=cls.others_company, title="Secret")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def edit_url(self, job: Job) -> str:
        return reverse("tracker:job_edit", args=[job.id])

    def post(self, job: Job, **fields: str) -> str:
        data = {"company": str(job.company.id), "title": job.title, **fields}
        return self.client.post(self.edit_url(job), data, follow=True).content.decode()

    def test_job_titles_link_to_their_view_page(self):
        page = self.client.get(reverse("tracker:jobs")).content.decode()
        view = reverse("tracker:job_detail", args=[self.job.id])
        self.assertIn(f'href="{view}"', page)
        self.assertNotIn(f'href="{self.edit_url(self.job)}"', page)
        self.assertNotIn("/admin/", page.split('id="jobs"')[1])

    def test_requires_login(self):
        self.client.logout()
        url = self.edit_url(self.job)
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_shows_the_current_values(self):
        response = self.client.get(self.edit_url(self.job))
        self.assertContains(response, "Edit Backend Engineer")
        self.assertContains(response, 'value="Austin"')
        self.assertContains(response, "Save changes")
        jobs_link = response.content.decode()
        jobs_link = jobs_link[jobs_link.index(f'href="{reverse("tracker:jobs")}"') :][
            :400
        ]
        self.assertIn("ring-white/6", jobs_link)  # Jobs nav stays active

    def test_saves_changes_and_returns_to_the_view_page(self):
        response = self.client.post(
            self.edit_url(self.job),
            {
                "company": str(self.globex.id),
                "title": "Staff Engineer",
                "workplace_type": "remote",
                "salary_min": "150000",
            },
            follow=True,
        )
        self.assertRedirects(
            response, reverse("tracker:job_detail", args=[self.job.id])
        )
        self.assertContains(response, "Saved Staff Engineer at Globex.")
        self.job.refresh_from_db()
        self.assertEqual(self.job.title, "Staff Engineer")
        self.assertEqual(self.job.company, self.globex)  # moved to another own company
        self.assertEqual(self.job.workplace_type, "remote")
        self.assertEqual(self.job.salary_min, 150000)
        self.assertEqual(self.job.location_city, "")  # cleared: not in the post

    def test_cannot_move_a_job_to_another_users_company(self):
        page = self.post(self.job, company=str(self.others_company.id))
        self.assertIn("Select a valid choice", page)
        self.job.refresh_from_db()
        self.assertEqual(self.job.company, self.acme)

    def test_validation_errors_keep_the_saved_title_in_the_heading(self):
        page = self.post(self.job, title="", salary_min="9", salary_max="1")
        self.assertIn("Edit Backend Engineer", page)
        self.assertIn("This field is required.", page)
        self.job.refresh_from_db()
        self.assertEqual(self.job.title, "Backend Engineer")

    def test_another_users_job_is_a_404(self):
        self.assertEqual(
            self.client.get(self.edit_url(self.others_job)).status_code, 404
        )
        response = self.client.post(
            self.edit_url(self.others_job),
            {"company": str(self.acme.id), "title": "Hacked"},
        )
        self.assertEqual(response.status_code, 404)
        self.others_job.refresh_from_db()
        self.assertEqual(self.others_job.title, "Secret")

    def test_add_page_still_has_its_own_heading_and_button(self):
        response = self.client.get(reverse("tracker:job_add"))
        self.assertContains(response, "<title>Add job · Job Tracker</title>")
        self.assertContains(response, "Add job\n        </button>")


class JobFormSkillsTests(TestCase):
    user: ClassVar[User]
    acme: ClassVar[Company]
    python: ClassVar[Skill]
    docker: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        cls.python = Skill.objects.create(name="Python")
        cls.docker = Skill.objects.create(name="Docker")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_add_form_has_the_skill_picker_over_a_multi_select(self):
        response = self.client.get(reverse("tracker:job_add"))
        self.assertContains(response, "data-skill-picker")
        self.assertContains(response, 'name="skills"')
        self.assertContains(response, " multiple")
        self.assertContains(
            response, f'<option value="{self.docker.id}">Docker</option>'
        )
        self.assertContains(
            response, f'<option value="{self.python.id}">Python</option>'
        )
        self.assertContains(response, "js/skill-picker.js")

    def test_add_form_saves_the_ticked_skills(self):
        _ = self.client.post(
            reverse("tracker:job_add"),
            {
                "company": str(self.acme.id),
                "title": "Backend Engineer",
                "skills": [str(self.python.id), str(self.docker.id)],
            },
        )
        job = Job.objects.get()
        self.assertEqual(set(job.skills.all()), {self.python, self.docker})

    def test_edit_form_shows_and_updates_skills(self):
        job = Job.objects.create(company=self.acme, title="Backend Engineer")
        job.skills.set([self.python])
        url = reverse("tracker:job_edit", args=[job.id])
        page = self.client.get(url).content.decode()
        self.assertIn(
            f'<option value="{self.python.id}" selected>Python</option>', page
        )
        self.assertIn(f'<option value="{self.docker.id}">Docker</option>', page)
        _ = self.client.post(
            url,
            {
                "company": str(self.acme.id),
                "title": "Backend Engineer",
                "skills": [str(self.docker.id)],
            },
        )
        self.assertEqual(list(job.skills.all()), [self.docker])

    def test_unticking_every_skill_clears_them(self):
        job = Job.objects.create(company=self.acme, title="Backend Engineer")
        job.skills.set([self.python, self.docker])
        _ = self.client.post(
            reverse("tracker:job_edit", args=[job.id]),
            {"company": str(self.acme.id), "title": "Backend Engineer"},
        )
        self.assertEqual(list(job.skills.all()), [])

    def test_rejects_an_unknown_skill(self):
        response = self.client.post(
            reverse("tracker:job_add"),
            {
                "company": str(self.acme.id),
                "title": "Backend Engineer",
                "skills": ["not-a-skill"],
            },
        )
        self.assertContains(response, "is not a valid value")
        self.assertFalse(Job.objects.exists())
