from collections.abc import Sequence
from typing import ClassVar, cast, override

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from ..models import Company, Job
from ..ownership import companies_for


class CompanyAddTests(TestCase):
    user: ClassVar[User]
    other: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")
        cls.other = User.objects.create_user("bob@example.com", "x")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def post(self, **fields: str) -> str:
        data = {"name": "Acme", "website": "", **fields}
        return self.client.post(
            reverse("tracker:company_add"), data, follow=True
        ).content.decode()

    def test_requires_login(self):
        self.client.logout()
        url = reverse("tracker:company_add")
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_page_renders_and_the_companies_page_links_to_it(self):
        self.assertContains(
            self.client.get(reverse("tracker:company_add")), "Add company"
        )
        add_link = f'href="{reverse("tracker:company_add")}"'
        self.assertContains(self.client.get(reverse("tracker:companies")), add_link)
        self.assertNotContains(self.client.get(reverse("tracker:dashboard")), add_link)

    def test_creates_a_company_owned_by_the_user(self):
        page = self.post(
            name="  Acme  ", website="acme.example", is_staffing_agency="on"
        )
        self.assertIn("Added Acme.", page)
        company = companies_for(self.user).get()
        self.assertEqual(company.name, "Acme")
        self.assertEqual(company.website, "https://acme.example")
        self.assertTrue(company.is_staffing_agency)

    def test_redirects_to_the_companies_page(self):
        response = self.client.post(reverse("tracker:company_add"), {"name": "Acme"})
        self.assertRedirects(response, reverse("tracker:companies"))

    def test_website_and_agency_are_optional(self):
        _ = self.post()
        company = companies_for(self.user).get()
        self.assertEqual(company.website, "")
        self.assertFalse(company.is_staffing_agency)

    def test_name_is_required(self):
        page = self.post(name="")
        self.assertIn("This field is required.", page)
        self.assertFalse(Company.objects.exists())

    def test_rejects_a_duplicate_name_ignoring_case(self):
        _ = Company.objects.create(user_owner=self.user, name="Acme")
        page = self.post(name="ACME")
        self.assertIn("You already have a company with this name.", page)
        self.assertEqual(companies_for(self.user).count(), 1)

    def test_duplicate_name_is_reported_alongside_other_errors(self):
        _ = Company.objects.create(user_owner=self.user, name="Acme")
        page = self.post(name="acme", website="not a url")
        self.assertIn("You already have a company with this name.", page)
        self.assertIn("Enter a valid URL.", page)

    def test_another_users_company_name_is_fine(self):
        _ = Company.objects.create(user_owner=self.other, name="Acme")
        _ = self.post(name="Acme")
        self.assertEqual(companies_for(self.user).count(), 1)

    def test_rejects_an_invalid_website(self):
        page = self.post(website="not a url")
        self.assertIn("Enter a valid URL.", page)
        self.assertFalse(Company.objects.exists())

    def test_owner_cannot_be_set_from_the_form(self):
        _ = self.post(name="Sneaky", user_owner=str(self.other.id))
        self.assertEqual(Company.objects.get(name="Sneaky").user_owner, self.user)

    def test_new_company_appears_in_the_jobs_page_company_filter(self):
        _ = self.post(name="Acme")
        _ = Company.objects.create(user_owner=self.other, name="Globex")
        response = self.client.get(reverse("tracker:jobs"))
        # The context is untyped; "companies" is the company filter's options.
        companies = cast(Sequence[Company], response.context["companies"])
        self.assertEqual([company.name for company in companies], ["Acme"])


class CompaniesPageTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")
        other = User.objects.create_user("bob@example.com", "x")
        acme = Company.objects.create(
            user_owner=cls.user, name="Acme", website="https://acme.example"
        )
        _ = Company.objects.create(
            user_owner=cls.user, name="Talentbridge", is_staffing_agency=True
        )
        _ = Company.objects.create(user_owner=other, name="Globex")
        for title in ("Backend Engineer", "Data Engineer"):
            _ = Job.objects.create(company=acme, title=title)

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        url = reverse("tracker:companies")
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_lists_only_the_users_companies_in_name_order(self):
        response = self.client.get(reverse("tracker:companies"))
        companies = cast(Sequence[Company], response.context["companies"])
        self.assertEqual([c.name for c in companies], ["Acme", "Talentbridge"])
        self.assertNotContains(response, "Globex")
        self.assertContains(response, "2 companies")

    def test_shows_website_type_and_job_count(self):
        page = self.client.get(reverse("tracker:companies")).content.decode()
        self.assertIn('href="https://acme.example"', page)
        self.assertIn('rel="noopener noreferrer"', page)
        self.assertRegex(page, r">\s*acme\.example\s*<svg")  # shown without https://
        self.assertIn("Staffing agency", page)
        self.assertRegex(page, r'tabular-nums">2</td>')

    def test_empty_state(self):
        _ = Company.objects.filter(user_owner=self.user).delete()
        response = self.client.get(reverse("tracker:companies"))
        self.assertContains(response, "No companies yet")
        self.assertContains(response, "Add your first company")

    def test_sidebar_link_is_active_on_the_list_and_add_pages(self):
        for name in ("tracker:companies", "tracker:company_add"):
            with self.subTest(name):
                page = self.client.get(reverse(name)).content.decode()
                companies_link = page[
                    page.index(f'href="{reverse("tracker:companies")}"') :
                ][:400]
                self.assertIn("ring-white/6", companies_link)

    def test_added_company_message_shows_on_the_companies_page(self):
        response = self.client.post(
            reverse("tracker:company_add"), {"name": "Initech"}, follow=True
        )
        self.assertContains(response, "Added Initech.")
        self.assertContains(response, "Initech")


class CompanyEditTests(TestCase):
    user: ClassVar[User]
    acme: ClassVar[Company]
    globex: ClassVar[Company]
    others: ClassVar[Company]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")
        other = User.objects.create_user("bob@example.com", "x")
        cls.acme = Company.objects.create(
            user_owner=cls.user, name="Acme", website="https://acme.example"
        )
        cls.globex = Company.objects.create(user_owner=cls.user, name="Globex")
        cls.others = Company.objects.create(user_owner=other, name="Initech")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def edit_url(self, company: Company) -> str:
        return reverse("tracker:company_edit", args=[company.id])

    def post(self, company: Company, **fields: str) -> str:
        data = {"name": company.name, "website": company.website, **fields}
        response = self.client.post(self.edit_url(company), data, follow=True)
        return response.content.decode()

    def test_edit_page_breadcrumb_and_cancel_lead_back_to_the_view_page(self):
        page = self.client.get(self.edit_url(self.acme)).content.decode()
        view = reverse("tracker:company_detail", args=[self.acme.id])
        self.assertEqual(page.count(f'href="{view}"'), 2)

    def test_requires_login(self):
        self.client.logout()
        url = self.edit_url(self.acme)
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_shows_the_current_values(self):
        response = self.client.get(self.edit_url(self.acme))
        self.assertContains(response, "Edit Acme")
        self.assertContains(response, 'value="https://acme.example"')
        self.assertContains(response, "Save changes")
        self.assertContains(response, 'ring-white/6">')  # Companies nav stays active

    def test_saves_changes(self):
        page = self.post(
            self.acme, name="Acme Corp", website="", is_staffing_agency="on"
        )
        self.assertIn("Saved Acme Corp.", page)
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.name, "Acme Corp")
        self.assertEqual(self.acme.website, "")
        self.assertTrue(self.acme.is_staffing_agency)

    def test_redirects_to_the_view_page(self):
        response = self.client.post(self.edit_url(self.acme), {"name": "Acme"})
        self.assertRedirects(
            response, reverse("tracker:company_detail", args=[self.acme.id])
        )

    def test_keeping_the_name_or_changing_its_case_is_fine(self):
        _ = self.post(self.acme)
        _ = self.post(self.acme, name="ACME")
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.name, "ACME")

    def test_rejects_the_name_of_another_of_your_companies(self):
        page = self.post(self.acme, name="globex")
        self.assertIn("You already have a company with this name.", page)
        self.assertIn("Edit Acme", page)  # heading keeps the saved name
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.name, "Acme")

    def test_another_users_company_is_a_404(self):
        self.assertEqual(self.client.get(self.edit_url(self.others)).status_code, 404)
        response = self.client.post(self.edit_url(self.others), {"name": "Hacked"})
        self.assertEqual(response.status_code, 404)
        self.others.refresh_from_db()
        self.assertEqual(self.others.name, "Initech")

    def test_add_page_still_has_its_own_heading_and_button(self):
        response = self.client.get(reverse("tracker:company_add"))
        self.assertContains(response, "<title>Add company · Job Tracker</title>")
        self.assertContains(response, "Add company\n      </button>")


class CompaniesPagingTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")
        other = User.objects.create_user("bob@example.com", "x")
        _ = Company.objects.bulk_create(
            Company(user_owner=cls.user, name=f"Company {n:03}") for n in range(105)
        )
        _ = Company.objects.bulk_create(
            Company(user_owner=other, name=f"Other {n:03}") for n in range(30)
        )

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def names(self, **params: str) -> list[str]:
        response = self.client.get(reverse("tracker:companies"), params)
        return [c.name for c in cast(Sequence[Company], response.context["companies"])]

    def test_shows_25_per_page_by_default(self):
        names = self.names()
        self.assertEqual(len(names), 25)
        self.assertEqual(names[0], "Company 000")
        response = self.client.get(reverse("tracker:companies"))
        self.assertContains(response, "Showing 1–25 of 105")
        self.assertContains(response, "105 companies")  # the total, not just this page

    def test_last_page_has_the_rest(self):
        self.assertEqual(
            self.names(page="5"), [f"Company {n:03}" for n in range(100, 105)]
        )

    def test_page_size_can_be_changed(self):
        self.assertEqual(len(self.names(per_page="100")), 100)
        self.assertEqual(self.names(per_page="50", page="2")[0], "Company 050")

    def test_bad_page_numbers_do_not_error(self):
        self.assertEqual(len(self.names(page="abc")), 25)  # falls back to page 1
        self.assertEqual(len(self.names(page="99")), 5)  # clamps to the last page

    def test_links_keep_the_page_size_and_return_to_the_list(self):
        response = self.client.get(reverse("tracker:companies"), {"per_page": "50"})
        self.assertContains(response, 'href="?per_page=50&amp;page=2#companies"')
        self.assertContains(response, 'id="companies"')

    def test_paging_footer_shows_even_for_a_short_list(self):
        _ = Company.objects.filter(
            user_owner=self.user, name__gte="Company 010"
        ).delete()
        response = self.client.get(reverse("tracker:companies"))
        self.assertContains(response, "10 companies")
        self.assertContains(response, "Showing 1–10 of 10")
        self.assertContains(response, "Per page")
        # A single page: Previous and Next are shown but disabled.
        self.assertContains(response, 'aria-disabled="true">Previous', count=1)
        self.assertContains(response, 'aria-disabled="true">Next', count=1)


class CompanyMissionStatementTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_add_form_saves_a_long_mission_statement_with_line_breaks(self):
        mission = "We make widgets people love.\n\n" + "Quality first. " * 200
        _ = self.client.post(
            reverse("tracker:company_add"),
            {"name": "Acme", "mission_statement": mission},
        )
        self.assertEqual(
            companies_for(self.user).get().mission_statement, mission.strip()
        )

    def test_mission_statement_is_optional(self):
        _ = self.client.post(reverse("tracker:company_add"), {"name": "Acme"})
        self.assertEqual(companies_for(self.user).get().mission_statement, "")

    def test_edit_form_shows_and_updates_the_mission_statement(self):
        company = Company.objects.create(
            user_owner=self.user, name="Acme", mission_statement="Old mission."
        )
        url = reverse("tracker:company_edit", args=[company.id])
        response = self.client.get(url)
        self.assertContains(response, "Mission statement")
        self.assertContains(response, ">\nOld mission.</textarea>")
        _ = self.client.post(url, {"name": "Acme", "mission_statement": "New mission."})
        company.refresh_from_db()
        self.assertEqual(company.mission_statement, "New mission.")

    def test_mission_statement_can_be_cleared(self):
        company = Company.objects.create(
            user_owner=self.user, name="Acme", mission_statement="Old mission."
        )
        url = reverse("tracker:company_edit", args=[company.id])
        _ = self.client.post(url, {"name": "Acme", "mission_statement": ""})
        company.refresh_from_db()
        self.assertEqual(company.mission_statement, "")


class CompanySearchTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")
        other = User.objects.create_user("bob@example.com", "x")
        for name, website in [
            ("Acme Robotics", "https://acme.example"),
            ("Globex", "https://globex-corp.example"),
            ("Initech", ""),
        ]:
            _ = Company.objects.create(user_owner=cls.user, name=name, website=website)
        _ = Company.objects.create(user_owner=other, name="Acme Elsewhere")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def search(self, **params: str) -> tuple[list[str], str]:
        response = self.client.get(reverse("tracker:companies"), params)
        page = cast(Sequence[Company], response.context["companies"])
        return [c.name for c in page], response.content.decode()

    def test_matches_names_ignoring_case(self):
        names, page = self.search(q="acme")
        self.assertEqual(
            names, ["Acme Robotics"]
        )  # not another user's "Acme Elsewhere"
        self.assertIn("1 of 3 companies", page)
        self.assertIn('value="acme"', page)

    def test_matches_websites(self):
        names, _ = self.search(q="globex-corp")
        self.assertEqual(names, ["Globex"])

    def test_no_matches_keeps_the_search_box(self):
        names, page = self.search(q="zzz")
        self.assertEqual(names, [])
        self.assertIn("No companies match &ldquo;zzz&rdquo;", page)
        self.assertIn('id="company-search"', page)
        self.assertNotIn("No companies yet", page)

    def test_clear_link_only_while_searching(self):
        _, page = self.search(q="acme")
        self.assertIn(">Clear</a>", page)
        _, page = self.search()
        self.assertNotIn(">Clear</a>", page)
        self.assertIn("3 companies", page)

    def test_page_links_keep_the_search_and_searching_resets_the_page(self):
        _ = Company.objects.bulk_create(
            Company(user_owner=self.user, name=f"Acme {n:02}") for n in range(30)
        )
        names, page = self.search(q="acme", page="2")
        self.assertEqual(len(names), 6)  # 31 matches: 25 on page 1, 6 on page 2
        self.assertIn('href="?q=acme&amp;page=1#companies"', page)
        # The search form has no page field, so a new search starts on page 1.
        self.assertNotIn('name="page"', page)

    def test_search_text_is_escaped(self):
        _, page = self.search(q='<script>alert("x")</script>')
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
