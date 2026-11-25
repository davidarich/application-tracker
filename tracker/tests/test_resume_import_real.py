"""The resume importer on a real resume (fixtures/dave-rich-resume.pdf).

A two-page, single-column resume: uppercase coloured headings, job dates
aligned right, the employer and location on the line under each job title,
descriptions that run onto the next page, no Summary heading (the summary is
the paragraph under the contact details) and no education section.
"""

from datetime import date
from pathlib import Path
from typing import ClassVar, override

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from ..models import Skill
from ..resume_import import ResumeExtraction, SkillOption, extract_lines, parse_resume
from .helpers import owner, temporary_media

RESUME_PDF = Path(__file__).parent / "fixtures" / "dave-rich-resume.pdf"

# The shared skills to match against (the seed skills when this was written).
SKILL_NAMES = [
    "Python", "JavaScript", "TypeScript", "Go", "Java", "C#", "Rust", "Kotlin", "Ruby",
    "SQL", "Django", "FastAPI", "Flask", "React", "Vue.js", "Angular", "Next.js",
    "Spring Boot", ".NET", "Ruby on Rails", "Docker", "Kubernetes", "Terraform",
    "Ansible", "GitHub Actions", "Jenkins", "Helm", "Prometheus", "Grafana", "Argo CD",
    "AWS Lambda", "Amazon S3", "Amazon EC2", "Amazon RDS", "Amazon DynamoDB",
    "Azure Functions", "Azure Kubernetes Service", "Azure Blob Storage",
    "Google Cloud Run", "Google BigQuery",
]  # fmt: skip
SKILLS = [SkillOption(str(index), name) for index, name in enumerate(SKILL_NAMES)]


class RealResumeTests(SimpleTestCase):
    result: ClassVar[ResumeExtraction]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.result = parse_resume(extract_lines(RESUME_PDF.read_bytes()), SKILLS)

    def test_summary_is_the_paragraph_under_the_contact_details(self):
        self.assertEqual(
            self.result.summary,
            "Software Engineer with seven years of experience specializing in Go, Kubernetes, "
            + "containers, CI/CD, and Linux. Over fifteen years of experience using and "
            + "maintaining Linux systems. Strong engineering fundamentals with AI-powered tools "
            + "enable me to build, iterate, and ship high quality software faster than ever.",
        )

    def test_every_position_with_its_title_employer_location_and_dates(self):
        self.assertEqual(
            [
                (job.title, job.employer, job.location, job.start_date, job.end_date)
                for job in self.result.work
            ],
            [
                ("Professional Development", "", "Pittsburgh, PA", date(2025, 11, 1), None),
                ("Cloud Software Engineer", "Webbula", "Wexford, PA", date(2023, 11, 1), date(2025, 10, 1)),
                ("Medical Leave", "", "Pittsburgh, PA", date(2022, 5, 1), date(2023, 10, 1)),
                ("Software Engineer", "Expedient", "Pittsburgh, PA", date(2017, 9, 1), date(2022, 4, 1)),
                ("Senior Technician", "Expedient", "Pittsburgh, PA", date(2017, 4, 1), date(2017, 9, 1)),
                ("Technician", "Expedient", "Pittsburgh, PA", date(2015, 3, 1), date(2017, 4, 1)),
                ("Analyst", "Expedient", "Pittsburgh, PA", date(2014, 8, 1), date(2015, 3, 1)),
            ],
        )  # fmt: skip

    def test_career_breaks_need_no_employer_and_are_not_flagged(self):
        self.assertEqual([job.title for job in self.result.work if job.uncertain], [])

    def test_descriptions_have_one_line_per_bullet_and_cross_pages(self):
        self.assertEqual(
            [len(job.description.splitlines()) for job in self.result.work],
            [4, 7, 1, 11, 4, 4, 3],
        )
        for job in self.result.work:
            for line in job.description.splitlines():
                self.assertTrue(line.startswith("- "), line)
                self.assertNotIn("●", line)
        webbula = self.result.work[1].description.splitlines()
        self.assertEqual(
            webbula[0],
            "- Created DNS parsing library for validating SPF, DKIM, and DMARC TXT records "
            + "according to RFC specifications with Go",
        )
        expedient = self.result.work[3].description.splitlines()
        self.assertTrue(
            expedient[5].startswith("- Optimized multi-region ETL")
        )  # page 2
        self.assertTrue(expedient[-1].endswith("monitoring and logging systems"))
        self.assertEqual(
            self.result.work[2].description, "- Returned to full capacity October 2023"
        )

    def test_certifications(self):
        self.assertEqual(
            [
                (cert.name, cert.issuer, cert.issued_on, cert.in_progress, cert.uncertain)
                for cert in self.result.certifications
            ],
            [
                # "Expected completion November 2026": in progress, expected then.
                ("Certified Kubernetes Administrator (CKA)", "Cloud Native Computing Foundation", date(2026, 11, 1), True, False),
                ("Certified Kubernetes Application Developer (CKAD)", "Cloud Native Computing Foundation", date(2026, 10, 1), False, False),
                # "Recertified September 2026" keeps the original issue date.
                ("AWS Certified Cloud Practitioner", "Amazon Web Services", date(2023, 9, 1), False, False),
            ],
        )  # fmt: skip

    def test_skills(self):
        self.assertEqual(
            sorted(SKILL_NAMES[int(skill_id)] for skill_id in self.result.skill_ids),
            sorted([
                "Go", "TypeScript", "JavaScript", "React", "Python", "SQL",
                "Kubernetes", "Docker", "Jenkins", "GitHub Actions", "Argo CD",
                "Grafana", "Prometheus", "Ansible", "Terraform",
                "Angular", "Amazon S3", "Amazon EC2",  # from the job descriptions
            ]),
        )  # fmt: skip
        # Everyday-word skills only count in the skills section: "Rust" is in a
        # job description but not the skills section.
        self.assertNotIn(SKILL_NAMES.index("Rust"), map(int, self.result.skill_ids))

    def test_no_education_and_only_the_expected_warning(self):
        self.assertEqual(self.result.education, [])
        self.assertEqual(self.result.warnings, [])


class RealResumeUploadTests(TestCase):
    @classmethod
    @override
    def setUpClass(cls) -> None:
        _ = temporary_media(cls)
        super().setUpClass()

    def test_upload_review_and_add(self):
        for name in ("Go", "Kubernetes", "Terraform"):
            _ = Skill.objects.create(name=name)
        self.client.force_login(owner())
        upload = SimpleUploadedFile(
            "Dave Rich - 2026 Web Resume.pdf", RESUME_PDF.read_bytes()
        )
        response = self.client.post(reverse("tracker:resume_import"), {"file": upload})
        self.assertRedirects(response, reverse("tracker:resume_import_review"))
        page = self.client.get(reverse("tracker:resume_import_review")).content.decode()
        self.assertEqual(page.count("Add this position"), 7)
        self.assertEqual(page.count("Add this certification"), 3)
        self.assertEqual(page.count(">Check this<"), 0)
        cka = page[page.index('value="Certified Kubernetes Administrator (CKA)"') :][
            :3000
        ]
        self.assertIn('name="certification-0-in_progress" class=', cka)
        self.assertIn(
            "checked", cka.split('name="certification-0-in_progress"')[1][:200]
        )
        self.assertIn('value="Webbula"', page)
        self.assertIn('value="2023-11"', page)
