"""creation_source: Manual for records made with the app's forms, API for
records made through the JSON API, never set from user input, and shown on
single-record pages only."""

from typing import ClassVar, cast, override

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from api.tests.helpers import ApiTestCase, Json

from ..models import Company, CreationSource, Job, Skill

MANUAL, API = CreationSource.MANUAL, CreationSource.API


class FormCreationTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("owner@example.com", "x", is_staff=True)

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_forms_create_manual_records_whatever_is_posted(self):
        _ = self.client.post(
            reverse("tracker:company_add"), {"name": "Acme", "creation_source": "api"}
        )
        company = Company.objects.get(name="Acme")
        _ = self.client.post(
            reverse("tracker:job_add"),
            {"company": str(company.id), "title": "Engineer", "creation_source": "api"},
        )
        _ = self.client.post(
            reverse("tracker:skill_add"), {"name": "Go", "creation_source": "api"}
        )
        self.assertEqual(company.creation_source, MANUAL)
        self.assertEqual(Job.objects.get(title="Engineer").creation_source, MANUAL)
        self.assertEqual(Skill.objects.get(name="Go").creation_source, MANUAL)

    def test_editing_keeps_the_creation_source(self):
        company = Company.objects.create(
            user_owner=self.user, name="Acme", creation_source=API
        )
        job = Job.objects.create(company=company, title="Engineer", creation_source=API)
        skill = Skill.objects.create(name="Go", creation_source=API)
        _ = self.client.post(
            reverse("tracker:company_edit", args=[company.id]),
            {"name": "Acme Inc", "creation_source": "manual"},
        )
        _ = self.client.post(
            reverse("tracker:job_edit", args=[job.id]),
            {"company": str(company.id), "title": "Lead", "creation_source": "manual"},
        )
        _ = self.client.post(
            reverse("tracker:skill_edit", args=[skill.id]),
            {"name": "Golang", "creation_source": "manual"},
        )
        company.refresh_from_db()
        job.refresh_from_db()
        skill.refresh_from_db()
        self.assertEqual(
            [(company.name, company.creation_source), (job.title, job.creation_source)],
            [("Acme Inc", API), ("Lead", API)],
        )
        self.assertEqual((skill.name, skill.creation_source), ("Golang", API))

    def test_shown_on_single_record_pages(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        job = Job.objects.create(company=company, title="Engineer", creation_source=API)
        skill = Skill.objects.create(name="Go", creation_source=API)

        def source(url: str) -> str:
            page = " ".join(self.client.get(url).content.decode().split())
            start = page.index("Creation source")
            return page[start : start + 200]

        self.assertIn(
            "Manual", source(reverse("tracker:company_detail", args=[company.id]))
        )
        self.assertIn("API", source(reverse("tracker:job_detail", args=[job.id])))
        self.assertIn("API", source(reverse("tracker:skill_edit", args=[skill.id])))

    def test_not_shown_in_tables_or_add_forms(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        _ = Job.objects.create(company=company, title="Engineer")
        _ = Skill.objects.create(name="Go")
        for name in (
            "companies",
            "jobs",
            "skills",
            "company_add",
            "job_add",
            "skill_add",
        ):
            page = self.client.get(reverse(f"tracker:{name}")).content.decode()
            self.assertNotIn("Creation source", page, name)
            self.assertNotIn('name="creation_source"', page, name)

    def test_read_only_in_the_admin(self):
        root = User.objects.create_superuser("root@example.com", "x")
        self.client.force_login(root)
        company = Company.objects.create(
            user_owner=self.user, name="Acme", creation_source=API
        )
        page = self.client.get(
            reverse("admin:tracker_company_change", args=[company.id])
        ).content.decode()
        self.assertIn("Creation source", page)
        self.assertNotIn('name="creation_source"', page)


class ApiCreationTests(ApiTestCase):
    def test_the_api_creates_api_records_whatever_is_sent(self):
        company = self.ok(
            "POST",
            "companies",
            {"name": "Acme", "creation_source": "manual"},
            status=201,
        )
        self.assertEqual(company["creation_source"], "api")
        job = self.ok(
            "POST",
            "jobs",
            {"company": company["id"], "title": "E", "creation_source": "manual"},
            status=201,
        )
        self.assertEqual(job["creation_source"], "api")
        self.assertEqual(Company.objects.get(id=company["id"]).creation_source, API)
        self.assertEqual(Job.objects.get(id=job["id"]).creation_source, API)

    def test_a_company_made_for_a_job_is_api_and_an_existing_one_is_unchanged(self):
        manual = Company.objects.create(user_owner=self.user, name="Globex")
        _ = self.ok(
            "POST", "jobs", {"company_name": "Initech", "title": "E"}, status=201
        )
        _ = self.ok(
            "POST", "jobs", {"company_name": "globex", "title": "E"}, status=201
        )
        self.assertEqual(Company.objects.get(name="Initech").creation_source, API)
        manual.refresh_from_db()
        self.assertEqual(manual.creation_source, MANUAL)

    def test_patch_never_changes_it(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        job = Job.objects.create(company=company, title="E")
        updated = self.ok(
            "PATCH",
            f"companies/{company.id}",
            {"name": "Acme 2", "creation_source": "api"},
        )
        self.assertEqual(
            (updated["name"], updated["creation_source"]), ("Acme 2", "manual")
        )
        updated = self.ok(
            "PATCH", f"jobs/{job.id}", {"title": "F", "creation_source": "api"}
        )
        self.assertEqual(updated["creation_source"], "manual")
        company.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(
            (company.creation_source, job.creation_source), (MANUAL, MANUAL)
        )

    def test_skills_added_by_staff_through_the_api_are_api(self):
        _ = User.objects.filter(id=self.user.id).update(is_staff=True)
        skill = self.ok(
            "POST", "skills", {"name": "Go", "creation_source": "manual"}, status=201
        )
        self.assertEqual(skill["creation_source"], "api")
        manual = Skill.objects.create(name="Rust")
        patched = self.ok("PATCH", f"skills/{manual.id}", {"creation_source": "api"})
        self.assertEqual(patched["creation_source"], "manual")
        listed = cast(list[Json], self.ok("GET", "skills")["items"])
        self.assertEqual(
            {cast(str, s["name"]): s["creation_source"] for s in listed},
            {"Go": "api", "Rust": "manual"},
        )
