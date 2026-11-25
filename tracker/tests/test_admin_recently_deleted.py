"""The Admin section's Recently deleted page: deleted shared records (skills so far)."""

from collections.abc import Sequence
from datetime import timedelta
from typing import ClassVar, cast, override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from ..models import Company, Job, Skill
from ..ownership import active_skills


class AdminRecentlyDeletedTests(TestCase):
    staff: ClassVar[User]
    perl: ClassVar[Skill]
    cobol: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        now = timezone.now()
        cls.staff = User.objects.create_user("staff@example.com", "x", is_staff=True)
        cls.perl = Skill.objects.create(
            name="Perl", description="Text processing.", is_deleted=True, deleted_at=now
        )
        cls.cobol = Skill.objects.create(
            name="COBOL", is_deleted=True, deleted_at=now - timedelta(days=2)
        )
        _ = Skill.objects.create(name="Python")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.staff)

    def test_route_is_generic_not_under_skills(self):
        url = reverse("tracker:admin_recently_deleted")
        self.assertEqual(url, "/manage/recently-deleted/")
        page = self.client.get(url).content.decode()
        self.assertIn("<title>Recently deleted · Admin · Job Tracker</title>", page)
        breadcrumb = page[page.index('aria-label="Breadcrumb"') :][:900]
        self.assertNotIn(f'href="{reverse("tracker:skills")}"', breadcrumb)

    def test_admin_section_links_to_it_between_skills_and_django_admin(self):
        page = self.client.get(
            reverse("tracker:admin_recently_deleted")
        ).content.decode()
        admin = page[page.index(">Admin</p>") : page.index(">Account</p>")]
        skills_at = admin.index(f'href="{reverse("tracker:skills")}"')
        deleted_at = admin.index(f'href="{reverse("tracker:admin_recently_deleted")}"')
        django_admin_at = admin.index(f'href="{reverse("admin:index")}"')
        self.assertLess(skills_at, deleted_at)
        self.assertLess(deleted_at, django_admin_at)
        self.assertIn('aria-current="page"', admin[deleted_at - 10 : deleted_at + 200])

    def test_lists_only_deleted_skills_newest_first(self):
        response = self.client.get(reverse("tracker:admin_recently_deleted"))
        skills = cast(Sequence[Skill], response.context["skills"])
        self.assertEqual([s.name for s in skills], ["Perl", "COBOL"])
        self.assertContains(response, "Text processing.")
        self.assertNotContains(response, ">Python<")

    def test_only_staff_can_see_it_or_restore(self):
        self.client.force_login(User.objects.create_user("ada@example.com", "x"))
        self.assertEqual(
            self.client.get(reverse("tracker:admin_recently_deleted")).status_code, 403
        )
        response = self.client.post(
            reverse("tracker:skill_restore", args=[self.perl.id])
        )
        self.assertEqual(response.status_code, 403)
        self.perl.refresh_from_db()
        self.assertTrue(self.perl.is_deleted)

    def test_other_users_have_no_link_to_it(self):
        self.client.force_login(User.objects.create_user("ada@example.com", "x"))
        page = self.client.get(reverse("tracker:jobs")).content.decode()
        self.assertNotIn(reverse("tracker:admin_recently_deleted"), page)

    def test_restore_brings_the_skill_back_on_its_jobs(self):
        company = Company.objects.create(user_owner=self.staff, name="Acme")
        job = Job.objects.create(company=company, title="Backend Engineer")
        job.skills.set([self.perl])
        response = self.client.post(
            reverse("tracker:skill_restore", args=[self.perl.id]), follow=True
        )
        self.assertRedirects(response, reverse("tracker:admin_recently_deleted"))
        self.assertContains(response, "Restored Perl.")
        self.perl.refresh_from_db()
        self.assertFalse(self.perl.is_deleted)
        self.assertIsNone(self.perl.deleted_at)
        self.assertIn(self.perl, active_skills())
        edit = self.client.get(reverse("tracker:job_edit", args=[job.id]))
        self.assertContains(edit, f'value="{self.perl.id}" selected')

    def test_restore_reports_a_name_clash(self):
        _ = Skill.objects.create(name="perl")
        response = self.client.post(
            reverse("tracker:skill_restore", args=[self.perl.id]), follow=True
        )
        self.assertContains(response, "Couldn&#x27;t restore Perl")
        self.perl.refresh_from_db()
        self.assertTrue(self.perl.is_deleted)

    def test_restore_requires_post_and_a_deleted_skill(self):
        url = reverse("tracker:skill_restore", args=[self.perl.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        active = Skill.objects.get(name="Python")
        response = self.client.post(reverse("tracker:skill_restore", args=[active.id]))
        self.assertEqual(response.status_code, 404)

    def test_empty_state(self):
        _ = Skill.objects.filter(is_deleted=True).delete()
        response = self.client.get(reverse("tracker:admin_recently_deleted"))
        self.assertContains(response, "No deleted skills.")
