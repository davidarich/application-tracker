"""The Recently deleted page: deleted companies and jobs, with Restore buttons."""

from collections.abc import Sequence
from datetime import timedelta
from typing import ClassVar, cast, override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from ..models import Company, Job
from ..ownership import companies_for, jobs_for


class RecentlyDeletedPageTests(TestCase):
    user: ClassVar[User]
    acme: ClassVar[Company]
    globex: ClassVar[Company]
    old_job: ClassVar[Job]
    new_job: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        now = timezone.now()
        cls.user = User.objects.create_user("ada@example.com", "x")
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        cls.globex = Company.objects.create(
            user_owner=cls.user, name="Globex", is_deleted=True, deleted_at=now
        )
        _ = Job.objects.create(company=cls.globex, title="Hidden With Globex")
        cls.old_job = Job.objects.create(
            company=cls.acme,
            title="Old Job",
            is_deleted=True,
            deleted_at=now - timedelta(days=3),
        )
        cls.new_job = Job.objects.create(
            company=cls.acme, title="New Job", is_deleted=True, deleted_at=now
        )
        other = User.objects.create_user("bob@example.com", "x")
        _ = Company.objects.create(user_owner=other, name="Initech", is_deleted=True)

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def page(self) -> str:
        return self.client.get(reverse("tracker:recently_deleted")).content.decode()

    def test_sidebar_link_is_under_profile(self):
        page = self.page()
        account = page[page.index(">Account</p>") :]
        profile_at = account.index(f'href="{reverse("accounts:profile")}"')
        deleted_at = account.index(f'href="{reverse("tracker:recently_deleted")}"')
        logout_at = account.index(f'action="{reverse("tracker:logout")}"')
        self.assertLess(profile_at, deleted_at)
        self.assertLess(deleted_at, logout_at)

    def test_requires_login(self):
        self.client.logout()
        url = reverse("tracker:recently_deleted")
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_lists_only_the_users_deleted_companies_and_jobs(self):
        response = self.client.get(reverse("tracker:recently_deleted"))
        companies = cast(Sequence[Company], response.context["companies"])
        jobs = cast(Sequence[Job], response.context["jobs"])
        self.assertEqual([c.name for c in companies], ["Globex"])  # not Bob's Initech
        # Newest first; a job hidden only because its company is deleted isn't listed.
        self.assertEqual([j.title for j in jobs], ["New Job", "Old Job"])

    def test_restore_a_company_brings_back_its_jobs(self):
        response = self.client.post(
            reverse("tracker:company_restore", args=[self.globex.id]), follow=True
        )
        self.assertRedirects(response, reverse("tracker:recently_deleted"))
        self.assertContains(response, "Restored Globex.")
        self.globex.refresh_from_db()
        self.assertFalse(self.globex.is_deleted)
        self.assertIsNone(self.globex.deleted_at)
        self.assertIn("Hidden With Globex", [j.title for j in jobs_for(self.user)])

    def test_restore_a_job(self):
        response = self.client.post(
            reverse("tracker:job_restore", args=[self.new_job.id]), follow=True
        )
        self.assertContains(response, "Restored New Job.")
        self.assertIn("New Job", [j.title for j in jobs_for(self.user)])

    def test_restoring_a_job_whose_company_is_deleted_explains_it_stays_hidden(self):
        job = Job.objects.create(
            company=self.globex, title="Twice Deleted", is_deleted=True
        )
        page = self.page()
        self.assertIn("also deleted", page)
        response = self.client.post(
            reverse("tracker:job_restore", args=[job.id]), follow=True
        )
        self.assertContains(
            response, "stays hidden until you restore its company, Globex"
        )

    def test_restore_reports_a_name_clash(self):
        _ = Company.objects.create(user_owner=self.user, name="globex")
        response = self.client.post(
            reverse("tracker:company_restore", args=[self.globex.id]), follow=True
        )
        self.assertContains(response, "Couldn&#x27;t restore Globex")
        self.globex.refresh_from_db()
        self.assertTrue(self.globex.is_deleted)

    def test_restore_requires_post_and_ownership(self):
        url = reverse("tracker:company_restore", args=[self.globex.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(User.objects.create_user("eve@example.com", "x"))
        self.assertEqual(self.client.post(url).status_code, 404)
        self.globex.refresh_from_db()
        self.assertTrue(self.globex.is_deleted)

    def test_empty_states(self):
        self.client.force_login(User.objects.create_user("new@example.com", "x"))
        page = self.page()
        self.assertIn("No deleted companies.", page)
        self.assertIn("No deleted jobs.", page)


class DeletedAtTests(TestCase):
    def test_delete_sets_and_undo_clears_the_timestamp(self):
        user = User.objects.create_user("ada@example.com", "x")
        company = Company.objects.create(user_owner=user, name="Acme")
        self.client.force_login(user)
        _ = self.client.post(reverse("tracker:company_delete", args=[company.id]))
        company.refresh_from_db()
        self.assertIsNotNone(company.deleted_at)
        _ = self.client.post(reverse("tracker:undo_delete"))
        company.refresh_from_db()
        self.assertIsNone(company.deleted_at)
        self.assertIn(company, companies_for(user))
