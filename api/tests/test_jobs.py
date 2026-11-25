"""The jobs endpoints: creating jobs (with a company by ID or name), changing
them and their status, and listing them."""

from typing import ClassVar, cast, get_args, override
from urllib.parse import urlencode

from accounts.models import User
from tracker.models import Application, ApplicationStatusChange, Company, Job, Skill

from ..schemas import StatusValue, WorkplaceValue
from .helpers import ApiTestCase, Json, items, names


class JobApiTests(ApiTestCase):
    acme: ClassVar[Company]
    python: ClassVar[Skill]
    go: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        cls.python = Skill.objects.create(name="Python")
        cls.go = Skill.objects.create(name="Go")

    def create(self, **fields: object) -> Json:
        return self.ok(
            "POST",
            "jobs",
            {"company": str(self.acme.id), "title": "Engineer", **fields},
            status=201,
        )

    def history(self, job_id: object) -> list[str]:
        return list(
            ApplicationStatusChange.objects.filter(application__job_id=job_id)
            .order_by("changed_at")
            .values_list("status", flat=True)
        )

    def test_schema_values_match_the_models(self):
        self.assertEqual(
            set(get_args(cast(object, StatusValue.__value__))),
            set(Application.Status.values),
        )
        self.assertEqual(
            set(get_args(cast(object, WorkplaceValue.__value__))),
            {"", *Job.WorkplaceType.values},
        )

    def test_create_with_a_company_id(self):
        job = self.create(
            title="Platform Engineer",
            posting_url="https://acme.example/jobs/1",
            location_city="Denver",
            location_state="CO",
            workplace_type="remote",
            salary_min=140000,
            salary_max=170000,
            description="Build things.",
        )
        expected: Json = {
            "title": "Platform Engineer",
            "company": {"id": str(self.acme.id), "name": "Acme"},
            "posting_url": "https://acme.example/jobs/1",
            "location_city": "Denver",
            "location_state": "CO",
            "workplace_type": "remote",
            "salary_min": 140000,
            "salary_max": 170000,
            "description": "Build things.",
            "skills": [],
            "status": None,
        }
        self.assertEqual({k: job[k] for k in expected}, expected)
        self.assertEqual(Job.objects.get(id=job["id"]).company, self.acme)
        self.assertEqual(self.history(job["id"]), [])  # not applied yet

    def test_skills_by_name_or_id_ignoring_case_without_repeats(self):
        job = self.create(skills=["PYTHON", str(self.go.id), " python "])
        self.assertEqual(names({"items": job["skills"]}), ["Go", "Python"])

    def test_unknown_or_deleted_skills_are_refused(self):
        _ = Skill.objects.create(name="Perl", is_deleted=True)
        errors = self.errors(
            "POST",
            "jobs",
            {
                "company": str(self.acme.id),
                "title": "E",
                "skills": ["Python", "Rust", "Perl"],
            },
        )
        self.assertEqual(
            errors,
            {"skills": ["Unknown skills: Rust, Perl. Only staff can add skills."]},
        )
        self.assertFalse(Job.objects.exists())

    def test_create_with_a_status_starts_its_history(self):
        job = self.create(status="applied")
        self.assertEqual(job["status"], "applied")
        self.assertEqual(self.history(job["id"]), ["applied"])

    def test_company_name_reuses_your_company_ignoring_case(self):
        job = self.ok(
            "POST", "jobs", {"company_name": " ACME ", "title": "E"}, status=201
        )
        self.assertEqual(job["company"], {"id": str(self.acme.id), "name": "Acme"})
        self.assertEqual(Company.objects.count(), 1)

    def test_company_name_creates_a_company_when_you_have_none_by_that_name(self):
        other = User.objects.create_user("bob@example.com", "x")
        theirs = Company.objects.create(user_owner=other, name="Globex")
        job = self.ok(
            "POST", "jobs", {"company_name": "Globex", "title": "E"}, status=201
        )
        company = Company.objects.get(id=cast(Json, job["company"])["id"])
        self.assertNotEqual(company, theirs)
        self.assertEqual((company.name, company.user_owner), ("Globex", self.user))

    def test_a_refused_job_does_not_leave_a_new_company_behind(self):
        errors = self.errors(
            "POST",
            "jobs",
            {"company_name": "Initech", "title": "E", "salary_min": 9, "salary_max": 1},
        )
        self.assertEqual(
            errors,
            {"non_field_errors": ["Minimum salary can't exceed maximum salary."]},
        )
        self.assertFalse(Company.objects.filter(name="Initech").exists())

    def test_the_company_must_be_given_once_and_be_yours(self):
        no_company = ["Give company (one of your company IDs) or company_name."]
        self.assertEqual(
            self.errors("POST", "jobs", {"title": "E"}), {"company": no_company}
        )
        self.assertEqual(
            self.errors("POST", "jobs", {"title": "E", "company_name": "  "}),
            {"company": no_company},
        )
        self.assertEqual(
            self.errors(
                "POST",
                "jobs",
                {"title": "E", "company": str(self.acme.id), "company_name": "Acme"},
            ),
            {"company": ["Give company or company_name, not both."]},
        )
        other = User.objects.create_user("bob@example.com", "x")
        theirs = Company.objects.create(user_owner=other, name="Bob Co")
        self.assertEqual(
            self.errors("POST", "jobs", {"title": "E", "company": str(theirs.id)}),
            {"company": ["You have no company with this ID."]},
        )
        self.assertIn(
            "company_name",
            self.errors("POST", "jobs", {"title": "E", "company_name": "x" * 201}),
        )

    def test_create_checks_the_fields(self):
        acme = str(self.acme.id)
        self.assertEqual(
            self.errors("POST", "jobs", {"company": acme})["title"], ["Field required"]
        )
        self.assertIn(
            "workplace_type",
            self.errors(
                "POST",
                "jobs",
                {"company": acme, "title": "E", "workplace_type": "moon"},
            ),
        )
        self.assertIn(
            "status",
            self.errors(
                "POST", "jobs", {"company": acme, "title": "E", "status": "hired"}
            ),
        )
        self.assertIn(
            "posting_url",
            self.errors(
                "POST", "jobs", {"company": acme, "title": "E", "posting_url": "nope"}
            ),
        )
        self.assertIn(
            "salary_min",
            self.errors(
                "POST", "jobs", {"company": acme, "title": "E", "salary_min": -1}
            ),
        )

    def test_malformed_json_is_refused(self):
        response = self.call("POST", "jobs", raw="{not json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", cast(Json, response.json()))

    def test_list_shows_your_jobs_with_filters_and_paging(self):
        applied = self.create(title="Applied one", status="applied")
        closed = self.create(title="Closed one", status="closed")
        _ = self.create(title="Not applied")
        globex = Company.objects.create(user_owner=self.user, name="Globex")
        _ = self.ok(
            "POST",
            "jobs",
            {"company": str(globex.id), "title": "At Globex"},
            status=201,
        )
        _ = Job.objects.create(company=self.acme, title="Deleted", is_deleted=True)
        other = User.objects.create_user("bob@example.com", "x")
        _ = Job.objects.create(
            company=Company.objects.create(user_owner=other, name="Bob Co"),
            title="Bob's",
        )

        page = self.ok("GET", "jobs")
        self.assertEqual(page["count"], 4)  # every status, unlike the site's default
        self.assertEqual(
            set(names(page, "title")),
            {"Applied one", "Closed one", "Not applied", "At Globex"},
        )
        self.assertEqual(
            names(self.ok("GET", "jobs?status=closed"), "title"), [closed["title"]]
        )
        self.assertNotIn(
            "Closed one", names(self.ok("GET", "jobs?status=open"), "title")
        )
        self.assertEqual(
            set(names(self.ok("GET", "jobs?status=none"), "title")),
            {"Not applied", "At Globex"},
        )
        self.assertEqual(
            names(self.ok("GET", f"jobs?company={globex.id}"), "title"), ["At Globex"]
        )
        self.assertEqual(
            names(self.ok("GET", "jobs?q=applied+one"), "title"), [applied["title"]]
        )
        self.assertEqual(names(self.ok("GET", "jobs?q=globex"), "title"), ["At Globex"])
        page = self.ok("GET", "jobs?limit=2&offset=3")
        self.assertEqual((page["count"], len(items(page))), (4, 1))
        self.assertIn("status", self.errors("GET", "jobs?status=nope"))

    def test_other_users_jobs_are_not_found(self):
        other = User.objects.create_user("bob@example.com", "x")
        theirs = Job.objects.create(
            company=Company.objects.create(user_owner=other, name="Bob Co"),
            title="Bob's",
        )
        for method, body in (("GET", None), ("PATCH", {"title": "Mine"})):
            response = self.call(method, f"jobs/{theirs.id}", body)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "No job with this ID."})
        self.assertEqual(Job.objects.get(id=theirs.id).title, "Bob's")

    def test_patch_changes_only_the_fields_sent(self):
        job = self.create(
            title="Engineer",
            location_city="Denver",
            salary_min=100,
            salary_max=200,
            skills=["Python"],
        )
        updated = self.ok(
            "PATCH",
            f"jobs/{job['id']}",
            {"title": "Senior Engineer", "salary_max": None},
        )
        self.assertEqual(
            (
                updated["title"],
                updated["location_city"],
                updated["salary_min"],
                updated["salary_max"],
            ),
            ("Senior Engineer", "Denver", 100, None),
        )
        self.assertEqual(names({"items": updated["skills"]}), ["Python"])
        updated = self.ok("PATCH", f"jobs/{job['id']}", {"skills": ["Go"]})
        self.assertEqual(names({"items": updated["skills"]}), ["Go"])
        self.assertEqual(
            self.ok("PATCH", f"jobs/{job['id']}", {"skills": []})["skills"], []
        )

    def test_patch_checks_the_fields(self):
        job = self.create()
        path = f"jobs/{job['id']}"
        self.assertIn("title", self.errors("PATCH", path, {"title": ""}))
        self.assertIn("title", self.errors("PATCH", path, {"title": None}))
        self.assertEqual(
            self.errors("PATCH", path, {"salary_min": 5, "salary_max": 1}),
            {"non_field_errors": ["Minimum salary can't exceed maximum salary."]},
        )
        self.assertEqual(
            self.errors("PATCH", path, {"company": None}),
            {"company": ["Give company (one of your company IDs) or company_name."]},
        )

    def test_patch_status_adds_to_the_history(self):
        job = self.create()
        path = f"jobs/{job['id']}"
        self.assertEqual(
            self.ok("PATCH", path, {"status": "applied"})["status"], "applied"
        )
        self.assertEqual(
            self.ok("PATCH", path, {"status": "interviewing"})["status"], "interviewing"
        )
        _ = self.ok(
            "PATCH", path, {"status": "interviewing"}
        )  # unchanged: not recorded again
        self.assertEqual(self.history(job["id"]), ["applied", "interviewing"])
        self.assertEqual(
            self.errors("PATCH", path, {"status": None}),
            {"status": ["A job's status can't be removed."]},
        )
        self.assertEqual(self.ok("GET", path)["status"], "interviewing")

    def test_patch_can_move_a_job_to_another_company(self):
        job = self.create()
        moved = self.ok("PATCH", f"jobs/{job['id']}", {"company_name": "Initech"})
        initech = Company.objects.get(user_owner=self.user, name="Initech")
        self.assertEqual(moved["company"], {"id": str(initech.id), "name": "Initech"})
        moved = self.ok("PATCH", f"jobs/{job['id']}", {"company": str(self.acme.id)})
        self.assertEqual(cast(Json, moved["company"])["name"], "Acme")

    def test_list_filters_by_posting_url(self):
        url = "https://acme.example/jobs/42"
        saved = self.create(title="Saved", posting_url=url, status="applied")
        _ = self.create(title="Other posting", posting_url=url + "1")
        _ = self.create(title="No link")
        other = User.objects.create_user("bob@example.com", "x")
        bob_co = Company.objects.create(user_owner=other, name="Bob Co")
        _ = Job.objects.create(company=bob_co, title="Bob's", posting_url=url)
        _ = Job.objects.create(
            company=self.acme, title="Deleted", posting_url=url, is_deleted=True
        )

        def titles(posting_url: str) -> list[str]:
            query = urlencode({"posting_url": posting_url})
            return names(self.ok("GET", "jobs?" + query), "title")

        # One request answers "is this posting saved?", whatever its status.
        page = self.ok("GET", "jobs?" + urlencode({"posting_url": url}))
        self.assertEqual((page["count"], names(page, "title")), (1, ["Saved"]))
        self.assertEqual(items(page)[0]["id"], saved["id"])
        self.assertEqual(
            titles(f"  {url}  "), ["Saved"]
        )  # spaces around it are ignored
        self.assertEqual(titles(url + "/"), ["Saved"])  # a copy of the same link
        self.assertEqual(
            titles("https://acme.example/jobs/4"), []
        )  # not a prefix search
        self.assertEqual(len(titles("")), 3)  # empty: no filter
        # It combines with the other filters.
        both = {"posting_url": url, "status": "closed"}
        self.assertEqual(names(self.ok("GET", "jobs?" + urlencode(both)), "title"), [])
        self.assertIn(
            # Up to 2000 characters: tracking parameters go before matching.
            "posting_url",
            self.errors("GET", "jobs?posting_url=" + "x" * 2001),
        )
