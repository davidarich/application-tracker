"""Each user sees only their own tracker data (see tracker/ownership.py)."""

import re
import tempfile
from io import StringIO
from typing import ClassVar, cast, override

from django.apps import apps
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, models
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from ..admin_ownership import SCOPED_CHOICE_MODELS
from ..charts import status_counts
from ..jobs import company_options
from ..models import (
    Application,
    ApplicationStatusChange,
    Company,
    Contact,
    CoverLetter,
    File,
    Job,
)
from ..ownership import (
    OWNER_PATHS,
    SHARED_MODELS,
    applications_for,
    companies_for,
    contacts_for,
    cover_letters_for,
    files_for,
    jobs_for,
    status_changes_for,
)


def make_user(email: str, *, superuser: bool = False, staff: bool = False) -> User:
    if superuser:
        return User.objects.create_superuser(email, "x")
    user = User.objects.create_user(email, "x", is_staff=staff)
    if staff:
        # Every tracker permission, so the admin's ownership limits are what's tested.
        user.user_permissions.set(
            Permission.objects.filter(content_type__app_label="tracker")
        )
    return user


def make_records(user: User, company_name: str) -> Job:
    """A company with a contact and a job, applied for, with a cover letter."""
    company = Company.objects.create(user_owner=user, name=company_name)
    _ = Contact.objects.create(company=company, name=f"Contact at {company_name}")
    job = Job.objects.create(company=company, title=f"Engineer at {company_name}")
    application = Application.objects.create(job=job)
    _ = CoverLetter.objects.create(application=application, contents="Hello")
    return job


class OwnershipMapTests(TestCase):
    def test_every_tracker_model_is_owned_or_deliberately_shared(self):
        self.assertEqual(
            set(OWNER_PATHS) | SHARED_MODELS,
            set(apps.get_app_config("tracker").get_models()),
        )
        self.assertFalse(set(OWNER_PATHS) & SHARED_MODELS)

    def test_every_tracker_foreign_key_has_scoped_choices(self):
        for model in apps.get_app_config("tracker").get_models():
            for field in model._meta.get_fields():
                if isinstance(field, models.ForeignKey):
                    related = cast(type[models.Model], field.related_model)
                    with self.subTest(model=model.__name__, field=field.name):
                        self.assertIn(related, SCOPED_CHOICE_MODELS)


class ScopedQuerySetTests(TestCase):
    alice: ClassVar[User]
    bob: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.alice = make_user("alice@example.com")
        cls.bob = make_user("bob@example.com")
        _ = make_records(cls.alice, "Acme")
        _ = make_records(cls.bob, "Globex")

    def test_each_function_returns_only_the_users_records(self):
        # (alice's records, everyone's records): one each for alice and bob.
        cases: dict[str, tuple[int, int]] = {
            "companies": (companies_for(self.alice).count(), Company.objects.count()),
            "contacts": (contacts_for(self.alice).count(), Contact.objects.count()),
            "jobs": (jobs_for(self.alice).count(), Job.objects.count()),
            "applications": (
                applications_for(self.alice).count(),
                Application.objects.count(),
            ),
            "cover letters": (
                cover_letters_for(self.alice).count(),
                CoverLetter.objects.count(),
            ),
            "status changes": (
                status_changes_for(self.alice).count(),
                ApplicationStatusChange.objects.count(),
            ),
        }
        for name, counts in cases.items():
            with self.subTest(name):
                self.assertEqual(counts, (1, 2))
        self.assertEqual(companies_for(self.alice).get().name, "Acme")

    def test_company_names_are_unique_per_user_ignoring_case(self):
        _ = Company.objects.create(
            user_owner=self.bob, name="ACME"
        )  # another user: fine
        with self.assertRaises(IntegrityError):
            _ = Company.objects.create(user_owner=self.alice, name="acme")

    def test_deleting_a_user_deletes_their_data(self):
        _ = self.bob.delete()
        self.assertEqual(set(Company.objects.values_list("name", flat=True)), {"Acme"})
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual(ApplicationStatusChange.objects.count(), 1)


class PageIsolationTests(TestCase):
    alice: ClassVar[User]
    bob: ClassVar[User]
    globex: ClassVar[Company]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.alice = make_user("alice@example.com")
        cls.bob = make_user("bob@example.com", superuser=True)
        _ = make_records(cls.alice, "Acme")
        cls.globex = make_records(cls.bob, "Globex").company

    def jobs_page(self, user: User, **params: str) -> str:
        self.client.force_login(user)
        return self.client.get(reverse("tracker:jobs"), params).content.decode()

    def test_job_table_and_company_filter_show_only_own_data(self):
        page = self.jobs_page(self.alice)
        self.assertIn("Engineer at Acme", page)
        self.assertNotIn("Globex", page)
        self.assertIn("1 job<", page)

    def test_another_users_company_id_matches_nothing(self):
        page = self.jobs_page(self.alice, company=str(self.globex.id))
        self.assertNotIn("Engineer at Globex", page)

    def test_superusers_jobs_page_shows_only_their_own_data(self):
        page = self.jobs_page(self.bob)
        self.assertIn("Engineer at Globex", page)
        self.assertNotIn("Acme", page)

    def test_chart_counts_only_own_applications(self):
        self.assertEqual(status_counts(self.alice).totals[-1], 1)
        _ = make_records(self.alice, "Initech")
        self.assertEqual(status_counts(self.alice).totals[-1], 2)
        self.assertEqual(status_counts(self.bob).totals[-1], 1)

    def test_company_options_are_own_companies(self):
        self.assertEqual([c.name for c in company_options(self.alice)], ["Acme"])

    def test_no_jobs_yet_when_only_other_users_have_jobs(self):
        carol = make_user("carol@example.com")
        self.assertIn("No jobs yet", self.jobs_page(carol))


class AdminOwnershipTests(TestCase):
    alice: ClassVar[User]
    staff: ClassVar[User]
    root: ClassVar[User]
    acme: ClassVar[Company]
    globex: ClassVar[Company]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.alice = make_user("alice@example.com")
        cls.staff = make_user("staff@example.com", staff=True)
        cls.root = make_user("root@example.com", superuser=True)
        cls.acme = make_records(cls.alice, "Acme").company
        cls.globex = make_records(cls.staff, "Globex").company

    def get(self, user: User, url: str) -> str:
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_superuser_sees_everyones_records_with_owner_column_and_filter(self):
        for name in ["company", "job", "contact", "application", "coverletter"]:
            with self.subTest(name):
                page = self.get(self.root, reverse(f"admin:tracker_{name}_changelist"))
                self.assertIn("alice@example.com", page)
                self.assertIn("staff@example.com", page)
                self.assertIn("User owner", page)

    def test_superuser_can_set_the_owner_of_a_new_company(self):
        self.client.force_login(self.root)
        response = self.client.post(
            reverse("admin:tracker_company_add"),
            {
                "user_owner": str(self.alice.id),
                "name": "Initech",
                "website": "",
                **INLINE_MANAGEMENT,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Company.objects.get(name="Initech").user_owner, self.alice)

    def test_new_company_defaults_to_the_current_user_as_owner(self):
        page = self.get(self.root, reverse("admin:tracker_company_add"))
        self.assertRegex(page, rf'<option value="{self.root.id}" selected>')

    def test_other_staff_see_only_their_own_records(self):
        page = self.get(self.staff, reverse("admin:tracker_company_changelist"))
        self.assertIn("Globex", page)
        self.assertNotIn("Acme", page)
        self.assertNotIn("User owner", page)
        job_page = self.get(self.staff, reverse("admin:tracker_job_changelist"))
        self.assertNotIn("Acme", job_page)  # including the company filter sidebar

    def test_other_staff_cannot_open_someone_elses_record(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("admin:tracker_company_change", args=[str(self.acme.id)])
        )
        self.assertRedirects(response, reverse("admin:index"))

    def test_other_staff_choices_are_limited_to_their_own(self):
        page = self.get(self.staff, reverse("admin:tracker_job_add"))
        self.assertNotIn(str(self.acme.id), page)
        company_page = self.get(self.staff, reverse("admin:tracker_company_add"))
        owner_options = re.findall(r'<option value="([0-9a-f-]{36})"', company_page)
        self.assertEqual(owner_options, [str(self.staff.id)])

    def test_other_staff_cannot_create_records_for_someone_else(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("admin:tracker_company_add"),
            {
                "user_owner": str(self.alice.id),
                "name": "Sneaky",
                "website": "",
                **INLINE_MANAGEMENT,
            },
        )
        self.assertEqual(response.status_code, 200)  # form redisplayed with an error
        self.assertFalse(Company.objects.filter(name="Sneaky").exists())


# Empty management forms for the company admin's contact and job inlines.
INLINE_MANAGEMENT = {
    f"{prefix}-{key}": value
    for prefix in ("contacts", "jobs")
    for key, value in {
        "TOTAL_FORMS": "0",
        "INITIAL_FORMS": "0",
        "MIN_NUM_FORMS": "0",
        "MAX_NUM_FORMS": "1000",
    }.items()
}


class FileOwnershipTests(TestCase):
    media: ClassVar[tempfile.TemporaryDirectory[str]]
    alice: ClassVar[User]
    bob: ClassVar[User]
    file: ClassVar[File]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        # Uploads go to a temporary folder, active before setUpTestData runs.
        cls.media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.media.cleanup)
        _ = cls.enterClassContext(override_settings(MEDIA_ROOT=cls.media.name))
        super().setUpClass()

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.alice = make_user("alice@example.com")
        cls.bob = make_user("bob@example.com")
        cls.file = File.objects.create(
            user_owner=cls.alice,
            name="Resume",
            path=SimpleUploadedFile("My Resume.PDF", b"%PDF-1.4 resume"),
        )

    def test_uploads_are_stored_under_the_owner_with_a_random_name(self):
        self.assertRegex(
            self.file.path.name, rf"^files/{self.alice.id}/[0-9a-f]{{32}}\.pdf$"
        )
        self.assertEqual(list(files_for(self.bob)), [])

    def test_owner_can_download_as_an_attachment(self):
        self.client.force_login(self.alice)
        response = self.client.get(self.file.path.url)
        self.assertEqual(response.status_code, 200)
        # Reading the file to the end also lets the test client close it
        # (Windows won't delete an open file). Don't call response.close():
        # it would close the database connection too, on databases that
        # really close it (PostgreSQL).
        self.assertEqual(response.getvalue(), b"%PDF-1.4 resume")
        self.assertIn(
            'attachment; filename="Resume.pdf"', response["Content-Disposition"]
        )

    def test_other_users_get_a_404(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.file.path.url).status_code, 404)

    def test_anonymous_visitors_must_log_in(self):
        response = self.client.get(self.file.path.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("tracker:login"), response["Location"])

    def test_superusers_can_download_any_file(self):
        self.client.force_login(make_user("root@example.com", superuser=True))
        response = self.client.get(self.file.path.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.getvalue(), b"%PDF-1.4 resume")  # and closes it

    def test_missing_file_is_a_404(self):
        gone = File.objects.create(
            user_owner=self.alice, name="Gone", path="files/gone.pdf"
        )
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(gone.path.url).status_code, 404)


@override_settings(DEBUG=True)
class SeedOwnershipTests(TestCase):
    def seed(self, *args: str) -> None:
        _ = call_command("seed", *args, stdout=StringIO())

    def test_seeds_and_clears_only_the_chosen_user(self):
        alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
        self.seed("--user", "alice@example.com", "--jobs", "5")
        self.seed("--user", "BOB@example.com", "--jobs", "7")
        self.assertEqual(jobs_for(alice).count(), 5)
        self.assertEqual(jobs_for(bob).count(), 7)
        self.seed("--user", "alice@example.com", "--jobs", "2", "--clear", "--noinput")
        self.assertEqual(jobs_for(alice).count(), 2)
        self.assertEqual(jobs_for(bob).count(), 7)

    def test_needs_a_user_choice_when_there_are_several(self):
        _ = make_user("alice@example.com"), make_user("bob@example.com")
        with self.assertRaisesMessage(CommandError, "--user"):
            self.seed("--jobs", "5")

    def test_unknown_user(self):
        _ = make_user("alice@example.com")
        with self.assertRaisesMessage(CommandError, "No user"):
            self.seed("--user", "nobody@example.com")

    def test_no_users_yet(self):
        with self.assertRaisesMessage(CommandError, "createsuperuser"):
            self.seed()
