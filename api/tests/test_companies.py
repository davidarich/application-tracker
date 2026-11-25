"""The companies endpoints: each user's own companies only."""

from accounts.models import User
from tracker.models import Company, Job

from .helpers import ApiTestCase, items, names


class CompanyApiTests(ApiTestCase):
    def test_create(self):
        company = self.ok(
            "POST",
            "companies",
            {
                "name": " Acme ",
                "website": "https://acme.example",
                "is_staffing_agency": True,
            },
            status=201,
        )
        self.assertEqual(
            {k: company[k] for k in ("name", "website", "mission_statement", "is_staffing_agency", "job_count")},
            {"name": "Acme", "website": "https://acme.example", "mission_statement": "", "is_staffing_agency": True, "job_count": 0},
        )  # fmt: skip
        saved = Company.objects.get(id=company["id"])
        self.assertEqual(saved.user_owner, self.user)

    def test_create_checks_the_fields(self):
        self.assertEqual(
            self.errors("POST", "companies", {})["name"], ["Field required"]
        )
        self.assertIn(
            "website",
            self.errors("POST", "companies", {"name": "A", "website": "nope"}),
        )
        self.assertIn(
            "Input should be a valid boolean",
            self.errors(
                "POST", "companies", {"name": "A", "is_staffing_agency": "maybe"}
            )["is_staffing_agency"][0],
        )

    def test_names_are_unique_per_user_ignoring_case(self):
        _ = Company.objects.create(user_owner=self.user, name="Acme")
        self.assertEqual(
            self.errors("POST", "companies", {"name": "ACME"}),
            {"name": ["You already have a company with this name."]},
        )
        other = User.objects.create_user("bob@example.com", "x")
        _ = Company.objects.create(user_owner=other, name="Globex")
        _ = self.ok("POST", "companies", {"name": "Globex"}, status=201)

    def test_list_shows_only_your_companies_by_name_with_search_and_paging(self):
        for name in ("beta", "Alpha", "Gamma"):
            _ = Company.objects.create(user_owner=self.user, name=name)
        _ = Company.objects.create(
            user_owner=self.user, name="Deleted", is_deleted=True
        )
        other = User.objects.create_user("bob@example.com", "x")
        _ = Company.objects.create(user_owner=other, name="Bob Co")
        page = self.ok("GET", "companies")
        self.assertEqual((page["count"], names(page)), (3, ["Alpha", "beta", "Gamma"]))
        self.assertEqual(names(self.ok("GET", "companies?q=MM")), ["Gamma"])
        page = self.ok("GET", "companies?limit=1&offset=1")
        self.assertEqual((page["count"], names(page)), (3, ["beta"]))
        self.assertIn("limit", self.errors("GET", "companies?limit=101"))

    def test_detail_counts_the_jobs_not_deleted(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        _ = Job.objects.create(company=company, title="One")
        _ = Job.objects.create(company=company, title="Gone", is_deleted=True)
        detail = self.ok("GET", f"companies/{company.id}")
        self.assertEqual((detail["name"], detail["job_count"]), ("Acme", 1))
        self.assertEqual(items(self.ok("GET", "companies"))[0]["job_count"], 1)

    def test_other_users_and_deleted_companies_are_not_found(self):
        other = User.objects.create_user("bob@example.com", "x")
        theirs = Company.objects.create(user_owner=other, name="Bob Co")
        gone = Company.objects.create(
            user_owner=self.user, name="Gone", is_deleted=True
        )
        for company in (theirs, gone):
            response = self.call("GET", f"companies/{company.id}")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "No company with this ID."})
            self.assertEqual(
                self.call(
                    "PATCH", f"companies/{company.id}", {"name": "Mine"}
                ).status_code,
                404,
            )
        self.assertEqual(Company.objects.get(id=theirs.id).name, "Bob Co")
        self.assertEqual(self.call("GET", "companies/not-an-id").status_code, 422)

    def test_patch_changes_only_the_fields_sent(self):
        company = Company.objects.create(
            user_owner=self.user,
            name="Acme",
            website="https://acme.example",
            is_staffing_agency=True,
        )
        updated = self.ok(
            "PATCH", f"companies/{company.id}", {"mission_statement": "Rockets."}
        )
        self.assertEqual(
            (
                updated["name"],
                updated["website"],
                updated["mission_statement"],
                updated["is_staffing_agency"],
            ),
            ("Acme", "https://acme.example", "Rockets.", True),
        )
        updated = self.ok(
            "PATCH",
            f"companies/{company.id}",
            {"is_staffing_agency": False, "website": ""},
        )
        self.assertEqual(
            (updated["is_staffing_agency"], updated["website"]), (False, "")
        )

    def test_patch_checks_the_fields(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        _ = Company.objects.create(user_owner=self.user, name="Globex")
        self.assertIn(
            "name", self.errors("PATCH", f"companies/{company.id}", {"name": None})
        )
        self.assertEqual(
            self.errors("PATCH", f"companies/{company.id}", {"name": "globex"}),
            {"name": ["You already have a company with this name."]},
        )
        # Renaming to its own name in another case is fine.
        self.assertEqual(
            self.ok("PATCH", f"companies/{company.id}", {"name": "ACME"})["name"],
            "ACME",
        )
