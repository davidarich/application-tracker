"""The Resume page: summary, work history, skills, education and certifications."""

from datetime import date
from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from ..models import Certification, Education, Resume, Skill, WorkExperience
from ..ownership import resume_for
from .helpers import owner

RESUME = reverse("tracker:resume")


def add_url(section: str) -> str:
    return reverse("tracker:resume_entry_add", args=[section])


class ResumePageTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def page(self) -> str:
        return self.client.get(RESUME).content.decode()

    def test_requires_login(self):
        self.client.logout()
        self.assertRedirects(
            self.client.get(RESUME), f"{reverse('tracker:login')}?next={RESUME}"
        )

    def test_shows_every_section_in_order_with_empty_states(self):
        page = self.page()
        ids = [
            'id="summary"',
            'id="work"',
            'id="skills"',
            'id="education"',
            'id="certifications"',
        ]
        positions = [page.index(section) for section in ids]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("No positions yet.", page)
        self.assertIn("No education yet.", page)
        self.assertIn("No certifications yet.", page)
        for section in ("work", "education", "certifications"):
            self.assertIn(f'href="{add_url(section)}"', page)

    def test_sidebar_links_to_resume(self):
        page = self.page()
        link = page[page.index(f'href="{RESUME}"') :][:200]
        self.assertIn('aria-current="page"', link)

    def test_saves_the_summary(self):
        response = self.client.post(
            RESUME, {"part": "summary", "summary": "Backend engineer."}
        )
        self.assertRedirects(
            response, f"{RESUME}#summary", fetch_redirect_response=False
        )
        self.assertEqual(resume_for(self.user).summary, "Backend engineer.")
        self.assertIn("Backend engineer.", self.page())

    def test_saves_skills_from_the_shared_list(self):
        python = Skill.objects.create(name="Python")
        go = Skill.objects.create(name="Go")
        gone = Skill.objects.create(name="Perl", is_deleted=True)
        response = self.client.post(
            RESUME, {"part": "skills", "skills": [python.id, go.id]}
        )
        self.assertRedirects(
            response, f"{RESUME}#skills", fetch_redirect_response=False
        )
        self.assertEqual(set(resume_for(self.user).skills.all()), {python, go})
        page = self.page()
        self.assertIn("data-skill-picker", page)
        self.assertNotIn(">Perl<", page)  # deleted skills aren't offered
        response = self.client.post(RESUME, {"part": "skills", "skills": [gone.id]})
        self.assertEqual(response.status_code, 200)  # not a valid choice
        self.assertEqual(set(resume_for(self.user).skills.all()), {python, go})

    def test_unknown_part_changes_nothing(self):
        response = self.client.post(RESUME, {"part": "other", "summary": "x"})
        self.assertRedirects(response, RESUME, fetch_redirect_response=False)
        self.assertEqual(resume_for(self.user).summary, "")


class ResumeEntryTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_add_work_history_with_month_dates(self):
        response = self.client.post(
            add_url("work"),
            {
                "title": "Engineer",
                "employer": "Acme",
                "start_date": "2021-03",
                "end_date": "",
                "description": "Built things.",
            },
        )
        self.assertRedirects(response, f"{RESUME}#work", fetch_redirect_response=False)
        job = WorkExperience.objects.get()
        self.assertEqual(job.user_owner, self.user)
        self.assertEqual(job.start_date, date(2021, 3, 1))
        self.assertIsNone(job.end_date)
        page = self.client.get(RESUME).content.decode()
        self.assertIn("Mar 2021 – Present", page)
        self.assertIn("Engineer", page)

    def test_month_inputs_and_optional_labels(self):
        page = self.client.get(add_url("work")).content.decode()
        self.assertIn('type="month" name="start_date"', page)
        self.assertIn('placeholder="YYYY-MM"', page)
        end = page[page.index('for="id_end_date"') :][:200]
        self.assertIn("(optional)", end)

    def test_employer_is_optional_for_career_breaks(self):
        page = self.client.get(add_url("work")).content.decode()
        employer = page[page.index('for="id_employer"') :][:200]
        self.assertIn("(optional)", employer)
        response = self.client.post(
            add_url("work"),
            {
                "title": "Sabbatical",
                "employer": "",
                "location": "Lisbon, Portugal",
                "start_date": "2023-01",
            },
        )
        self.assertRedirects(response, f"{RESUME}#work", fetch_redirect_response=False)
        leave = WorkExperience.objects.get()
        self.assertEqual((leave.employer, str(leave)), ("", "Sabbatical"))
        page = self.client.get(RESUME).content.decode()
        self.assertIn(">Lisbon, Portugal</p>", page)  # no stray separator
        self.assertNotIn("> · ", page)

    def test_education_in_progress_shows_its_expected_completion(self):
        page = self.client.get(add_url("education")).content.decode()
        self.assertIn('name="in_progress"', page)
        self.assertIn("Still in progress", page)
        _ = self.client.post(
            add_url("education"),
            {
                "institution": "State University",
                "degree": "MS",
                "start_date": "2024-09",
                "end_date": "2026-05",
                "in_progress": "on",
            },
        )
        school = Education.objects.get()
        self.assertTrue(school.in_progress)
        page = self.client.get(RESUME).content.decode()
        self.assertIn("Sep 2024 – Expected May 2026", " ".join(page.split()))
        _ = Education.objects.filter(id=school.id).update(end_date=None)
        page = self.client.get(RESUME).content.decode()
        self.assertIn("Sep 2024 – In progress", " ".join(page.split()))

    def test_certification_in_progress_is_expected_not_issued_or_expired(self):
        _ = self.client.post(
            add_url("certifications"),
            {"name": "CKA", "issued_on": "2026-11", "in_progress": "on"},
        )
        cert = Certification.objects.get()
        self.assertTrue(cert.in_progress)
        _ = Certification.objects.filter(id=cert.id).update(expires_on=date(2020, 1, 1))
        page = self.client.get(RESUME).content.decode()
        self.assertIn("Expected Nov 2026", page)
        self.assertNotIn("Issued Nov 2026", page)
        self.assertNotIn("Expired", page)
        _ = Certification.objects.filter(id=cert.id).update(
            issued_on=None, expires_on=None
        )
        self.assertIn(">In progress</p>", self.client.get(RESUME).content.decode())

    def test_entries_are_not_in_progress_by_default(self):
        _ = self.client.post(
            add_url("certifications"), {"name": "Done Cert", "issued_on": "2020-01"}
        )
        self.assertFalse(Certification.objects.get().in_progress)
        self.assertIn("Issued Jan 2020", self.client.get(RESUME).content.decode())

    def test_end_before_start_is_refused(self):
        response = self.client.post(
            add_url("work"),
            {
                "title": "Engineer",
                "employer": "Acme",
                "start_date": "2022-05",
                "end_date": "2021-01",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "This can&#x27;t be before the start date.", response.content.decode()
        )
        self.assertFalse(WorkExperience.objects.exists())

    def test_work_history_lists_current_positions_first(self):
        _ = WorkExperience.objects.create(
            user_owner=self.user,
            title="Old",
            employer="A",
            start_date=date(2015, 1, 1),
            end_date=date(2018, 1, 1),
        )
        _ = WorkExperience.objects.create(
            user_owner=self.user, title="Now", employer="B", start_date=date(2019, 1, 1)
        )
        _ = WorkExperience.objects.create(
            user_owner=self.user,
            title="Recent",
            employer="C",
            start_date=date(2018, 1, 1),
            end_date=date(2019, 1, 1),
        )
        page = self.client.get(RESUME).content.decode()
        self.assertLess(page.index(">Now<"), page.index(">Recent<"))
        self.assertLess(page.index(">Recent<"), page.index(">Old<"))

    def test_add_education(self):
        response = self.client.post(
            add_url("education"),
            {
                "institution": "State University",
                "degree": "BS",
                "field_of_study": "Computer Science",
                "end_date": "2014-05",
            },
        )
        self.assertRedirects(
            response, f"{RESUME}#education", fetch_redirect_response=False
        )
        page = self.client.get(RESUME).content.decode()
        self.assertIn("State University", page)
        self.assertIn("BS, Computer Science", page)
        self.assertIn("May 2014", page)

    def test_add_certification_and_show_expiry(self):
        response = self.client.post(
            add_url("certifications"),
            {
                "name": "Cloud Architect",
                "issuer": "Example Cloud",
                "issued_on": "2020-01",
                "expires_on": "2023-01",
                "credential_url": "https://example.com/verify/1",
            },
        )
        self.assertRedirects(
            response, f"{RESUME}#certifications", fetch_redirect_response=False
        )
        self.assertEqual(Certification.objects.get().user_owner, self.user)
        page = self.client.get(RESUME).content.decode()
        self.assertIn("Expired Jan 2023", page)
        self.assertIn(
            'href="https://example.com/verify/1" target="_blank" rel="noopener noreferrer"',
            page,
        )

    def test_edit_and_delete_an_entry(self):
        school = Education.objects.create(user_owner=self.user, institution="Old Name")
        edit = reverse("tracker:resume_entry_edit", args=["education", school.id])
        page = self.client.get(edit).content.decode()
        self.assertIn('value="Old Name"', page)
        self.assertIn('id="delete-form"', page)
        _ = self.client.post(edit, {"institution": "New Name"})
        school.refresh_from_db()
        self.assertEqual(school.institution, "New Name")
        delete = reverse("tracker:resume_entry_delete", args=["education", school.id])
        self.assertEqual(self.client.get(delete).status_code, 405)
        response = self.client.post(delete, follow=True)
        self.assertIn("Deleted New Name.", response.content.decode())
        school.refresh_from_db()
        self.assertTrue(school.is_deleted)  # soft deleted, so it can be restored

    def test_unknown_section_is_404(self):
        self.assertEqual(self.client.get(add_url("hobbies")).status_code, 404)


class ResumeOwnershipTests(TestCase):
    def test_users_only_see_and_change_their_own_resume(self):
        alice, bob = owner(), User.objects.create_user("bob@example.com", "x")
        resume = Resume.objects.create(user_owner=alice, summary="Alice's summary")
        cert = Certification.objects.create(user_owner=alice, name="Alice Cert")
        self.client.force_login(bob)
        page = self.client.get(RESUME).content.decode()
        self.assertNotIn("Alice", page)
        edit = reverse("tracker:resume_entry_edit", args=["certifications", cert.id])
        delete = reverse(
            "tracker:resume_entry_delete", args=["certifications", cert.id]
        )
        self.assertEqual(self.client.get(edit).status_code, 404)
        self.assertEqual(self.client.post(edit, {"name": "Hacked"}).status_code, 404)
        self.assertEqual(self.client.post(delete).status_code, 404)
        # The wrong section for an entry is a 404 too.
        self.client.force_login(alice)
        self.assertEqual(
            self.client.get(
                reverse("tracker:resume_entry_edit", args=["work", cert.id])
            ).status_code,
            404,
        )
        cert.refresh_from_db()
        resume.refresh_from_db()
        self.assertEqual((cert.name, resume.summary), ("Alice Cert", "Alice's summary"))
