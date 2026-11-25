"""The MCP server's tools: the same behaviour as the JSON API's endpoints,
for the user of the access token, with failures as tool errors."""

import uuid
from typing import ClassVar, cast, override

from mcp.client import Client
from mcp.client.client import ConnectMode
from mcp_types import Tool

from accounts.models import User
from tracker.models import Application, ApplicationStatusChange, Company, Job, Skill

from .helpers import Json, McpTestCase, items, names

ALL_TOOLS = {
    "list_jobs",
    "get_job",
    "create_job",
    "update_job",
    "set_job_status",
    "list_companies",
    "get_company",
    "create_company",
    "update_company",
    "list_skills",
    "get_skill",
    "create_skill",
    "update_skill",
}
STAFF_TOOLS = {"create_skill", "update_skill"}


class ToolListTests(McpTestCase):
    def test_staff_only_tools_are_listed_only_to_staff(self):
        self.assertEqual(self.tool_names(), ALL_TOOLS - STAFF_TOOLS)
        _ = User.objects.filter(id=self.user.id).update(is_staff=True)
        self.assertEqual(self.tool_names(), ALL_TOOLS)

    def test_tools_are_described_for_agents(self):
        async def work(client: Client) -> list[Tool]:
            return (await client.list_tools()).tools

        tools = {tool.name: tool for tool in self.session(work)}
        annotations = {
            name: tool.annotations
            for name, tool in tools.items()
            if tool.annotations is not None
        }
        self.assertEqual(set(annotations), ALL_TOOLS - STAFF_TOOLS)
        self.assertTrue(annotations["list_jobs"].read_only_hint)
        self.assertFalse(annotations["create_job"].read_only_hint)
        self.assertFalse(annotations["update_job"].destructive_hint)
        description = tools["create_job"].description or ""
        self.assertIn("posting_url", description)
        # Docstrings are dedented.
        self.assertNotIn("\n    ", description)
        self.assertIsNotNone(tools["get_job"].output_schema)


class JobToolTests(McpTestCase):
    acme: ClassVar[Company]
    python: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        cls.python = Skill.objects.create(name="Python")

    def create(self, **job: object) -> Json:
        return self.ok("create_job", job={"company": str(self.acme.id), **job})

    def test_create_a_job(self):
        job = self.create(
            title="Platform Engineer",
            posting_url="https://acme.example/jobs/1",
            skills=["python"],
            status="applied",
        )
        self.assertEqual(job["title"], "Platform Engineer")
        self.assertEqual(job["company"], {"id": str(self.acme.id), "name": "Acme"})
        self.assertEqual(job["skills"], [{"id": str(self.python.id), "name": "Python"}])
        self.assertEqual(job["status"], "applied")
        self.assertEqual(job["creation_source"], "mcp")
        saved = Job.objects.get(id=cast(str, job["id"]))
        self.assertEqual(saved.creation_source, "mcp")
        self.assertEqual(saved.title, "Platform Engineer")

    def test_a_company_named_for_a_job_is_created_and_marked_as_mcp(self):
        job = self.ok("create_job", job={"title": "SRE", "company_name": "Globex"})
        company = Company.objects.get(name="Globex")
        self.assertEqual(company.user_owner, self.user)
        self.assertEqual(company.creation_source, "mcp")
        self.assertEqual(job["company"], {"id": str(company.id), "name": "Globex"})
        # An existing company is matched ignoring case.
        again = self.ok("create_job", job={"title": "Dev", "company_name": "acme"})
        self.assertEqual(cast(Json, again["company"])["id"], str(self.acme.id))

    def test_invalid_fields_are_a_tool_error_listing_them(self):
        message = self.error(
            "create_job",
            job={"title": "SRE", "company": str(self.acme.id), "skills": ["Cobol"]},
        )
        self.assertIn("Some fields aren't valid.", message)
        self.assertIn(
            "- skills: Unknown skills: Cobol. Only staff can add skills.", message
        )
        message = self.error("create_job", job={"title": "SRE"})
        self.assertIn("- company: Give company", message)
        self.assertFalse(Job.objects.exists())

    def test_arguments_of_the_wrong_shape_are_a_tool_error(self):
        message = self.error("get_job", job_id="not-a-uuid")
        self.assertIn("job_id", message)
        message = self.error("list_jobs", limit=1000)
        self.assertIn("limit", message)

    def test_list_and_filter_jobs(self):
        first = self.create(title="Backend", posting_url="https://acme.example/jobs/7")
        _ = self.create(title="Frontend", status="interviewing")
        self.assertEqual(names(self.ok("list_jobs"), "title"), ["Frontend", "Backend"])
        self.assertEqual(
            names(self.ok("list_jobs", status="interviewing"), "title"), ["Frontend"]
        )
        self.assertEqual(names(self.ok("list_jobs", q="back"), "title"), ["Backend"])
        # The same posting, with tracking parameters added.
        found = self.ok(
            "list_jobs", posting_url="https://www.acme.example/jobs/7?utm_source=x"
        )
        self.assertEqual([job["id"] for job in items(found)], [first["id"]])
        page = self.ok("list_jobs", limit=1, offset=1)
        self.assertEqual(page["count"], 2)
        self.assertEqual(names(page, "title"), ["Backend"])

    def test_update_changes_only_the_fields_given(self):
        job = self.create(title="Backend", location_city="Denver", salary_min=100)
        changed = self.ok(
            "update_job", job_id=job["id"], changes={"title": "Senior Backend"}
        )
        self.assertEqual(changed["title"], "Senior Backend")
        self.assertEqual(changed["location_city"], "Denver")
        self.assertEqual(changed["salary_min"], 100)
        message = self.error("update_job", job_id=job["id"], changes={"status": None})
        self.assertIn("A job's status can't be removed.", message)

    def test_set_job_status_records_the_history(self):
        job = self.create(title="Backend")
        self.assertIsNone(job["status"])
        _ = self.ok("set_job_status", job_id=job["id"], status="applied")
        changed = self.ok("set_job_status", job_id=job["id"], status="interviewing")
        self.assertEqual(changed["status"], "interviewing")
        history = ApplicationStatusChange.objects.filter(
            application__job_id=cast(str, job["id"])
        ).order_by("changed_at")
        self.assertEqual(
            list(history.values_list("status", flat=True)), ["applied", "interviewing"]
        )
        message = self.error("set_job_status", job_id=job["id"], status="hired")
        self.assertIn("status", message)
        self.assertEqual(Application.objects.count(), 1)

    def test_other_users_jobs_are_not_found(self):
        other = User.objects.create_user("other@example.com", "x")
        theirs = Job.objects.create(
            company=Company.objects.create(user_owner=other, name="Initech"),
            title="Secret",
        )
        message = self.error("get_job", job_id=str(theirs.id))
        self.assertIn("No job with this ID.", message)
        message = self.error(
            "update_job", job_id=str(theirs.id), changes={"title": "Mine"}
        )
        self.assertIn("No job with this ID.", message)
        self.assertEqual(self.ok("list_jobs")["count"], 0)
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "Secret")
        # Nor can their companies be used.
        message = self.error(
            "create_job", job={"title": "x", "company": str(theirs.company.id)}
        )
        self.assertIn("You have no company with this ID.", message)

    def test_unknown_ids_are_not_found(self):
        message = self.error("get_job", job_id=str(uuid.uuid4()))
        self.assertIn("No job with this ID.", message)


class CompanyToolTests(McpTestCase):
    def test_create_list_get_and_update_companies(self):
        created = self.ok(
            "create_company",
            company={"name": "Globex", "website": "https://globex.example"},
        )
        self.assertEqual(created["creation_source"], "mcp")
        self.assertEqual(created["job_count"], 0)
        _ = self.ok("create_company", company={"name": "Acme"})
        self.assertEqual(names(self.ok("list_companies")), ["Acme", "Globex"])
        self.assertEqual(names(self.ok("list_companies", q="glob")), ["Globex"])
        got = self.ok("get_company", company_id=created["id"])
        self.assertEqual(got["website"], "https://globex.example")
        changed = self.ok(
            "update_company",
            company_id=created["id"],
            changes={"is_staffing_agency": True},
        )
        self.assertTrue(changed["is_staffing_agency"])
        self.assertEqual(changed["website"], "https://globex.example")

    def test_company_names_are_unique_ignoring_case(self):
        _ = self.ok("create_company", company={"name": "Acme"})
        message = self.error("create_company", company={"name": "ACME"})
        self.assertIn("- name:", message)

    def test_other_users_companies_are_not_found(self):
        other = User.objects.create_user("other@example.com", "x")
        theirs = Company.objects.create(user_owner=other, name="Initech")
        message = self.error("get_company", company_id=str(theirs.id))
        self.assertIn("No company with this ID.", message)
        self.assertEqual(self.ok("list_companies")["count"], 0)


class SkillToolTests(McpTestCase):
    python: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.python = Skill.objects.create(name="Python", description="A language")

    def test_anyone_can_read_skills(self):
        self.assertEqual(names(self.ok("list_skills")), ["Python"])
        self.assertEqual(names(self.ok("list_skills", q="language")), ["Python"])
        got = self.ok("get_skill", skill_id=str(self.python.id))
        self.assertEqual(got["description"], "A language")

    def test_only_staff_can_add_or_change_skills(self):
        # Hidden from the list, and refused if called anyway.
        message = self.error("create_skill", skill={"name": "Go"})
        self.assertIn("Only staff can add or change skills.", message)
        message = self.error(
            "update_skill", skill_id=str(self.python.id), changes={"name": "Py"}
        )
        self.assertIn("Only staff can add or change skills.", message)
        self.assertFalse(Skill.objects.filter(name="Go").exists())

        _ = User.objects.filter(id=self.user.id).update(is_staff=True)
        created = self.ok("create_skill", skill={"name": "Go"})
        self.assertEqual(created["creation_source"], "mcp")
        changed = self.ok(
            "update_skill", skill_id=str(self.python.id), changes={"name": "Python 3"}
        )
        self.assertEqual(changed["name"], "Python 3")
        self.assertEqual(changed["description"], "A language")


class ModernProtocolTests(McpTestCase):
    """The newest protocol revision (negotiated, no initialize handshake)."""

    mode: ConnectMode = "auto"

    def test_tools_work(self):
        self.assertEqual(self.tool_names(), ALL_TOOLS - STAFF_TOOLS)
        created = self.ok("create_company", company={"name": "Acme"})
        self.assertEqual(created["creation_source"], "mcp")
        self.assertIn(
            "No job with this ID.", self.error("get_job", job_id=str(uuid.uuid4()))
        )
