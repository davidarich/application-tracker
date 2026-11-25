"""Detecting the hiring system (ATS) from a job posting link."""

from typing import ClassVar, override

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from api.tests.helpers import ApiTestCase

from ..hiring_systems import HIRING_SYSTEMS, detect_hiring_system
from ..models import Company, Job

# One or more example links per system.
EXAMPLES: dict[str, list[str]] = {
    "Workday": [
        "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Remote/Engineer_R123",
        "https://acme.wd12.myworkdayjobs.com/careers",
        "https://myworkdayjobs.com/acme",
    ],
    "Greenhouse": [
        "https://boards.greenhouse.io/acme/jobs/4567",
        "https://job-boards.greenhouse.io/acme/jobs/4567",
        "https://boards.eu.greenhouse.io/acme/jobs/4567",
        "https://job-boards.eu.greenhouse.io/acme/jobs/4567",
        "https://acme.com/careers?gh_jid=4567",
    ],
    "Lever": [
        "https://jobs.lever.co/acme/0a1b2c3d-1234",
        "https://jobs.eu.lever.co/acme/0a1b2c3d-1234",
    ],
    "Ashby": [
        "https://jobs.ashbyhq.com/acme/0a1b2c3d",
        "https://acme.com/careers?ashby_jid=0a1b2c3d",
    ],
    "SmartRecruiters": [
        "https://jobs.smartrecruiters.com/Acme/7430000001234-engineer",
        "https://careers.smartrecruiters.com/Acme/engineering",
    ],
    "iCIMS": [
        "https://careers-acme.icims.com/jobs/1234/engineer/job",
        "https://uscareers-acme.icims.com/jobs/1234/job",
    ],
    "Comeet": [
        "https://www.comeet.com/jobs/acme/A1.234/engineer/B2.345",
        "https://www.comeet.co/jobs/acme/A1.234/engineer/B2.345",
    ],
    "Spark Hire": ["https://app.sparkhire.com/interview/abc"],
    "Workable": [
        "https://apply.workable.com/acme/j/ABC123/",
        "https://acme.workable.com/j/ABC123",
        "https://acme.workable.com/jobs/123456",
    ],
    "BambooHR": ["https://acme.bamboohr.com/careers/42"],
    "Teamtailor": ["https://acme.teamtailor.com/jobs/1234-engineer"],
    "Jobvite": [
        "https://jobs.jobvite.com/acme/job/oAbC123",
        "https://careers.jobvite.com/acme/job/oAbC123",
        "https://app.jobvite.com/CompanyJobs/Careers.aspx?c=qAbC&jobId=oAbC123",
    ],
    "Oracle Taleo": ["https://acme.taleo.net/careersection/2/jobdetail.ftl?job=12345"],
    "SAP SuccessFactors": [
        "https://career5.successfactors.com/career?company=Acme&career_job_req_id=88",
        "https://career2.successfactors.eu/career?company=Acme",
        "https://career5.sapsf.com/career?company=Acme",
        "https://careers.sapsf.com/career?company=Acme",
        "https://jobs.sap.com/job/Walldorf-Developer/1234567/",
    ],
    "Recruitee": ["https://acme.recruitee.com/o/engineer"],
    "Personio": [
        "https://acme.jobs.personio.de/job/123456",
        "https://acme.jobs.personio.com/job/123456",
        "https://acme.personio.de/job/123456",
    ],
    "Breezy HR": ["https://acme.breezy.hr/p/abc123-engineer"],
    "JazzHR": ["https://acme.applytojob.com/apply/AbC123/Engineer"],
}

NOT_RECOGNISED = [
    "https://acme.com/careers/engineer",  # a company's own site, no tracking code
    "https://www.linkedin.com/jobs/view/123",  # Easy Apply can't be told from a link
    "https://www.indeed.com/viewjob?jk=abc",  # a job board repost
    "https://greenhouse.io/blog",  # the vendor's own site, not a job board
    "https://www.icims.com/products",  # iCIMS, but not /jobs
    "https://www.comeet.com/pricing",
    "https://lever.co/",
    "https://bamboohr.com/pricing",  # not a company subdomain
    "https://evil-myworkdayjobs.com/acme",  # only looks like it
    "https://boards.greenhouse.io.evil.example/acme",
    "https://acme.com/careers?gh_jid_x=1",
    "https://resources.workable.com/hiring-guide",  # Workable's own site
    "https://www.personio.de/hr-lexicon/",  # Personio's own site
    "https://support.personio.de/hc/en-us",
    "https://www.comeet.co/pricing",
    "https://www.sap.com/products",
    "https://www.jobvite.com/blog",
    "https://xyz.boards.greenhouse.io.example/acme",
    "",
    "not a link",
]


class DetectionTests(SimpleTestCase):
    def test_every_system_has_examples(self):
        self.assertEqual(set(EXAMPLES), {system.name for system in HIRING_SYSTEMS})
        self.assertEqual(len(EXAMPLES), 18)

    def test_examples_are_detected(self):
        for name, urls in EXAMPLES.items():
            for url in urls:
                system = detect_hiring_system(url)
                self.assertEqual(system.name if system else None, name, url)

    def test_other_links_are_not_recognised(self):
        for url in NOT_RECOGNISED:
            self.assertIsNone(detect_hiring_system(url), url)

    def test_case_www_and_extra_parts_do_not_matter(self):
        for url in (
            "HTTPS://Jobs.Lever.CO/acme/1",
            "https://jobs.lever.co:443/acme/1?x=1#apply",
            "https://www.comeet.com/jobs/acme/1",
            "https://comeet.com/jobs/acme/1",
            "https://acme.com/careers?GH_JID=1",
        ):
            self.assertIsNotNone(detect_hiring_system(url), url)

    def test_the_board_wins_over_a_tracking_code(self):
        system = detect_hiring_system("https://jobs.ashbyhq.com/acme/1?gh_jid=2")
        self.assertEqual(system.name if system else None, "Ashby")


class JobPageTests(TestCase):
    user: ClassVar[User]
    company: ClassVar[Company]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("owner@example.com", "x")
        cls.company = Company.objects.create(user_owner=cls.user, name="Acme")

    def hiring_system_shown(self, posting_url: str) -> str:
        job = Job.objects.create(
            company=self.company, title="E", posting_url=posting_url
        )
        self.client.force_login(self.user)
        page = self.client.get(
            reverse("tracker:job_detail", args=[job.id])
        ).content.decode()
        section = " ".join(page[page.index("Hiring system") :].split())
        return section.split("<dd", 1)[1].split(">", 1)[1].split("</dd>", 1)[0].strip()

    def test_the_job_page_shows_the_hiring_system(self):
        self.assertEqual(
            self.hiring_system_shown("https://jobs.lever.co/acme/1"), "Lever"
        )
        self.assertEqual(
            self.hiring_system_shown("https://acme.com/jobs/1"), "Not recognised"
        )
        self.assertEqual(self.hiring_system_shown(""), "No posting link")


class ApiTests(ApiTestCase):
    def test_jobs_include_the_hiring_system(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        job = self.ok(
            "POST",
            "jobs",
            {
                "company": str(company.id),
                "title": "E",
                "posting_url": "https://acme.com/c?gh_jid=1",
            },
            status=201,
        )
        self.assertEqual(job["hiring_system"], "Greenhouse")
        job = self.ok("PATCH", f"jobs/{job['id']}", {"posting_url": ""})
        self.assertIsNone(job["hiring_system"])
