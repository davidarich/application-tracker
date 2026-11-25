"""Filling in the resume from a PDF: the upload and review pages."""

from datetime import date
from typing import ClassVar, override

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from ..models import Certification, Education, Skill, WorkExperience
from ..ownership import resume_for
from ..resume_import import (
    CertificationEntry,
    EducationEntry,
    ResumeExtraction,
    WorkEntry,
)
from ..resume_import.session import to_session
from ..resume_import_views import SESSION_KEY
from .helpers import owner, temporary_media
from .pdf_builder import Text, build_pdf, column

UPLOAD = reverse("tracker:resume_import")
REVIEW = reverse("tracker:resume_import_review")
RESUME = reverse("tracker:resume")


def resume_pdf() -> bytes:
    b, n = True, False
    texts = column(
        40,
        60,
        [
            ("SUMMARY", 12, b),
            ("Backend engineer who likes building reliable APIs.", 10, n),
            ("EXPERIENCE", 12, b),
            ("Senior Software Engineer", 10, b),
            ("Driftwood Software Inc. | Austin, TX", 10, n),
            ("• Led the move to services.", 10, n),
            ("SKILLS", 12, b),
            ("Python, Django", 10, n),
        ],
    )
    return build_pdf([[*texts, Text(450, texts[4].y, "Mar 2021 – Present")]])


class UploadTests(TestCase):
    @classmethod
    @override
    def setUpClass(cls) -> None:
        _ = temporary_media(cls)
        super().setUpClass()

    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def upload(self, data: bytes, name: str = "resume.pdf") -> str:
        response = self.client.post(UPLOAD, {"file": SimpleUploadedFile(name, data)})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_requires_login(self):
        self.client.logout()
        for url in (UPLOAD, REVIEW):
            self.assertRedirects(
                self.client.get(url), f"{reverse('tracker:login')}?next={url}"
            )

    def test_resume_page_links_to_the_upload_page(self):
        page = self.client.get(RESUME).content.decode()
        self.assertIn(f'href="{UPLOAD}"', page)
        self.assertIn("Fill in from resume", page)

    def test_shows_the_upload_form(self):
        page = self.client.get(UPLOAD).content.decode()
        self.assertIn('enctype="multipart/form-data"', page)
        self.assertIn('accept=".pdf,application/pdf"', page)
        self.assertIn('ring-white/6">', page)  # Resume nav stays active

    def test_rejects_files_that_are_not_pdfs(self):
        self.assertIn("Upload a PDF file.", self.upload(b"hello", "resume.txt"))
        self.assertIn("Upload a PDF file.", self.upload(b"hello", "resume.pdf"))

    def test_rejects_big_files(self):
        page = self.upload(b"%PDF" + b"0" * (5 * 1024 * 1024), "big.pdf")
        self.assertIn("This file is too big.", page)

    def test_explains_pdfs_it_cannot_read(self):
        self.assertIn("No text was found in this PDF.", self.upload(build_pdf([[]])))
        self.assertIn("couldn&#x27;t be read as a PDF", self.upload(b"%PDF-1.4 broken"))

    def test_a_resume_is_parsed_and_reviewed(self):
        _ = Skill.objects.create(name="Python")
        response = self.client.post(
            UPLOAD, {"file": SimpleUploadedFile("resume.pdf", resume_pdf())}
        )
        self.assertRedirects(response, REVIEW, fetch_redirect_response=False)
        page = self.client.get(REVIEW).content.decode()
        self.assertIn("Backend engineer who likes building reliable APIs.", page)
        self.assertIn('value="Senior Software Engineer"', page)
        self.assertIn('value="Driftwood Software Inc."', page)
        self.assertIn('value="Austin, TX"', page)
        self.assertIn('value="2021-03"', page)
        skills = page.split('id="import-skills-title"')[1].split("</section>")[0]
        self.assertIn("Python", skills)
        self.assertEqual(WorkExperience.objects.count(), 0)  # nothing saved yet


class ReviewTests(TestCase):
    user: ClassVar[User]
    python: ClassVar[Skill]
    go: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()
        cls.python = Skill.objects.create(name="Python")
        cls.go = Skill.objects.create(name="Go")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)
        self.store(
            ResumeExtraction(
                summary="Backend engineer.",
                work=[
                    WorkEntry(
                        "Engineer",
                        "Acme Inc.",
                        "Remote",
                        date(2021, 3, 1),
                        None,
                        "Built things.",
                    ),
                    WorkEntry(
                        "Wrangler",
                        "",
                        "",
                        date(2015, 1, 1),
                        date(2016, 1, 1),
                        uncertain=True,
                    ),
                ],
                education=[
                    EducationEntry(
                        "State University", "BS", "Math", None, date(2014, 5, 1)
                    )
                ],
                certifications=[
                    CertificationEntry(
                        "Cloud Architect", "Example Cloud", date(2022, 4, 1)
                    )
                ],
                skill_ids=[str(self.python.id), str(self.go.id)],
                warnings=[
                    "1 entry couldn't be read with confidence and is marked “Check this”."
                ],
            )
        )

    def store(self, extraction: ResumeExtraction) -> None:
        session = self.client.session
        session[SESSION_KEY] = to_session(extraction)
        session.save()

    def form_data(self, **overrides: str | list[str]) -> dict[str, str | list[str]]:
        data: dict[str, str | list[str]] = {
            "summary": "Backend engineer.",
            "replace_summary": "on",
            "skills": [str(self.python.id), str(self.go.id)],
            "work-0-include": "on",
            "work-0-title": "Engineer",
            "work-0-employer": "Acme Inc.",
            "work-0-location": "Remote",
            "work-0-start_date": "2021-03",
            "work-0-end_date": "",
            "work-0-description": "Built things.",
            "work-1-title": "Wrangler",
            "work-1-employer": "",
            "work-1-start_date": "2015-01",
            "work-1-end_date": "2016-01",
            "education-0-include": "on",
            "education-0-institution": "State University",
            "education-0-degree": "BS",
            "education-0-field_of_study": "Math",
            "education-0-end_date": "2014-05",
            "certification-0-include": "on",
            "certification-0-name": "Cloud Architect",
            "certification-0-issuer": "Example Cloud",
            "certification-0-issued_on": "2022-04",
        }
        data.update(overrides)
        return data

    def test_without_an_upload_goes_to_the_upload_page(self):
        session = self.client.session
        del session[SESSION_KEY]
        session.save()
        self.assertRedirects(self.client.get(REVIEW), UPLOAD)

    def test_shows_entries_warnings_and_flags(self):
        page = self.client.get(REVIEW).content.decode()
        self.assertIn("marked “Check this”", page)
        self.assertEqual(page.count(">Check this<"), 1)
        self.assertIn('name="work-0-include" checked', page)
        self.assertIn('value="Acme Inc."', page)
        self.assertIn('name="replace_summary" checked', page)  # no summary yet
        self.assertIn("Use this as my summary", page)
        self.assertNotIn("autofocus", page.split("<main")[1])

    def test_adds_the_chosen_entries(self):
        response = self.client.post(REVIEW, self.form_data(), follow=True)
        self.assertRedirects(response, RESUME)
        self.assertContains(
            response,
            "Added 1 position, 1 school, 1 certification, 2 skills to your resume and replaced your summary.",
        )
        job = WorkExperience.objects.get()
        self.assertEqual(
            (job.user_owner, job.title, job.start_date, job.end_date),
            (self.user, "Engineer", date(2021, 3, 1), None),
        )
        self.assertEqual(Education.objects.get().end_date, date(2014, 5, 1))
        self.assertEqual(Certification.objects.get().issued_on, date(2022, 4, 1))
        resume = resume_for(self.user)
        self.assertEqual(resume.summary, "Backend engineer.")
        self.assertEqual(set(resume.skills.all()), {self.python, self.go})
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_edits_on_the_review_page_are_saved(self):
        _ = self.client.post(
            REVIEW, self.form_data(**{"work-0-title": "Staff Engineer"})
        )
        self.assertEqual(WorkExperience.objects.get().title, "Staff Engineer")

    def test_invalid_chosen_entries_stop_everything_and_show_errors(self):
        data = self.form_data(**{"work-1-include": "on", "work-1-start_date": ""})
        response = self.client.post(REVIEW, data)
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn("Some entries need fixing", page)
        self.assertIn("This field is required.", page)
        self.assertFalse(WorkExperience.objects.exists())
        self.assertFalse(Education.objects.exists())
        self.assertIn(SESSION_KEY, self.client.session)

    def test_positions_without_an_employer_can_be_added(self):
        _ = self.client.post(REVIEW, self.form_data(**{"work-1-include": "on"}))
        wrangler = WorkExperience.objects.get(title="Wrangler")
        self.assertEqual(wrangler.employer, "")

    def test_entries_left_out_are_not_checked_or_saved(self):
        data = self.form_data(**{"work-1-employer": ""})
        response = self.client.post(REVIEW, data, follow=True)
        self.assertRedirects(response, RESUME)
        self.assertEqual(
            list(WorkExperience.objects.values_list("title", flat=True)), ["Engineer"]
        )

    def test_keeps_the_current_summary_unless_asked(self):
        resume = resume_for(self.user)
        resume.summary = "My own summary."
        resume.save()
        page = self.client.get(REVIEW).content.decode()
        self.assertIn("Replace my current summary with this", page)
        self.assertNotIn('name="replace_summary" checked', page)
        data = self.form_data()
        del data["replace_summary"]
        _ = self.client.post(REVIEW, data)
        resume.refresh_from_db()
        self.assertEqual(resume.summary, "My own summary.")

    def test_skills_already_on_the_resume_are_shown_but_not_offered(self):
        resume_for(self.user).skills.add(self.go)
        page = self.client.get(REVIEW).content.decode()
        self.assertNotIn(f'value="{self.go.id}"', page)
        self.assertIn('title="Already on your resume"', page)
        _ = self.client.post(REVIEW, self.form_data(skills=[str(self.python.id)]))
        self.assertEqual(
            set(resume_for(self.user).skills.all()), {self.python, self.go}
        )

    def test_skills_not_found_cannot_be_added(self):
        other = Skill.objects.create(name="Rust")
        _ = self.client.post(REVIEW, self.form_data(skills=[str(other.id)]))
        self.assertEqual(list(resume_for(self.user).skills.all()), [])

    def test_entries_already_on_the_resume_start_unticked(self):
        _ = WorkExperience.objects.create(
            user_owner=self.user,
            title="engineer",
            employer="ACME INC.",
            start_date=date(2021, 3, 1),
        )
        page = self.client.get(REVIEW).content.decode()
        self.assertIn("Already on your resume", page)
        self.assertNotIn('name="work-0-include" checked', page)

    def test_damaged_session_data_goes_back_to_upload(self):
        session = self.client.session
        session[SESSION_KEY] = {"work": [{"start_date": "not a date"}]}
        session.save()
        self.assertRedirects(self.client.get(REVIEW), UPLOAD)
