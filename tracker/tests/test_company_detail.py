"""The View company page."""

from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from ..models import Company, Contact, Job
from .helpers import Status, make_job_with_status, owner


class CompanyDetailTests(TestCase):
    acme: ClassVar[Company]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.acme = Company.objects.create(
            user_owner=owner(),
            name="Acme",
            website="https://acme.example",
            mission_statement="Make everything.",
            is_staffing_agency=True,
        )

    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def url(self, company: Company | None = None) -> str:
        return reverse("tracker:company_detail", args=[(company or self.acme).id])

    def page(self) -> str:
        return self.client.get(self.url()).content.decode()

    def test_requires_login(self):
        self.client.logout()
        url = self.url()
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_company_names_in_the_table_link_to_the_view_page(self):
        page = self.client.get(reverse("tracker:companies")).content.decode()
        self.assertIn(f'href="{self.url()}"', page)
        self.assertNotIn(reverse("tracker:company_edit", args=[self.acme.id]), page)

    def test_shows_the_details_and_an_edit_button(self):
        page = self.page()
        self.assertIn("<h1", page)
        self.assertIn("Acme", page)
        self.assertIn("Staffing agency", page)
        self.assertIn(
            'href="https://acme.example" target="_blank" rel="noopener noreferrer"',
            page,
        )
        self.assertIn("Make everything.", page)
        edit = reverse("tracker:company_edit", args=[self.acme.id])
        button = page[page.index(f'href="{edit}"') :][:1200]
        self.assertIn("Edit company", button)
        self.assertIn('ring-white/6">', page)  # Companies nav stays active

    def test_missing_details_have_fallbacks(self):
        bare = Company.objects.create(user_owner=owner(), name="Bare")
        page = self.client.get(self.url(bare)).content.decode()
        self.assertIn("Not listed", page)
        self.assertIn("Not added yet.", page)
        self.assertNotIn("Staffing agency", page)
        self.assertIn("No jobs at Bare yet.", page)

    def test_lists_all_the_companys_jobs_with_their_status(self):
        open_job = make_job_with_status(
            "Engineer", "Acme", Status.INTERVIEWING, timezone.now()
        )
        closed = make_job_with_status("Designer", "Acme", Status.CLOSED, timezone.now())
        deleted = make_job_with_status("Gone", "Acme", Status.APPLIED, timezone.now())
        _ = Job.objects.filter(id=deleted.id).update(is_deleted=True)
        _ = make_job_with_status("Elsewhere", "Globex", Status.APPLIED, timezone.now())
        page = self.page()
        for job in (open_job, closed):
            self.assertIn(
                f'href="{reverse("tracker:job_detail", args=[job.id])}"', page
            )
        self.assertIn("Interviewing", page)
        self.assertIn("Closed", page)  # finished jobs are listed too
        self.assertIn("2 jobs", page)
        self.assertNotIn("Gone", page)
        self.assertNotIn("Elsewhere", page)

    def test_other_users_and_deleted_companies_are_404(self):
        theirs = Company.objects.create(
            user_owner=User.objects.create_user("bob@example.com", "x"), name="Bob Co"
        )
        self.assertEqual(self.client.get(self.url(theirs)).status_code, 404)
        _ = Company.objects.filter(id=self.acme.id).update(is_deleted=True)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_contacts_section_is_above_jobs(self):
        _ = Contact.objects.create(
            company=self.acme,
            name="Zoe Recruiter",
            email="zoe@acme.example",
            phone_number="+1 512-555-0100",
            linkedin_url="https://example.com/in/zoe",
        )
        _ = Contact.objects.create(company=self.acme, name="Adam Bare")
        globex = Company.objects.create(user_owner=owner(), name="Globex")
        _ = Contact.objects.create(company=globex, name="Not Here")
        page = self.page()
        self.assertLess(
            page.index('id="contacts-title"'), page.index('id="company-jobs-title"')
        )
        self.assertIn("2 contacts", page)
        self.assertLess(page.index("Adam Bare"), page.index("Zoe Recruiter"))
        self.assertIn('href="mailto:zoe@acme.example"', page)
        self.assertIn('href="tel:+1 512-555-0100"', page)
        self.assertIn(
            'href="https://example.com/in/zoe" target="_blank" rel="noopener noreferrer"',
            page,
        )
        self.assertIn("No email or phone", page)
        self.assertNotIn("Not Here", page)

    def test_no_contacts(self):
        self.assertIn("No contacts at Acme yet.", self.page())
