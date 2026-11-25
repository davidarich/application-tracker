"""Undoing a soft delete from the "Deleted …" message."""

from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from ..models import Company, Job, Skill
from ..ownership import active_skills, companies_for, jobs_for


class UndoDeleteTests(TestCase):
    user: ClassVar[User]
    acme: ClassVar[Company]
    job: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x", is_staff=True)
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        cls.job = Job.objects.create(company=cls.acme, title="Backend Engineer")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def undo(self) -> str:
        return self.client.post(
            reverse("tracker:undo_delete"), follow=True
        ).content.decode()

    def test_deleted_message_offers_undo(self):
        response = self.client.post(
            reverse("tracker:company_delete", args=[self.acme.id]), follow=True
        )
        self.assertContains(response, "Deleted Acme.")
        self.assertContains(response, f'action="{reverse("tracker:undo_delete")}"')
        self.assertContains(response, "Undo")

    def test_undo_restores_a_company_and_its_jobs(self):
        _ = self.client.post(reverse("tracker:company_delete", args=[self.acme.id]))
        page = self.undo()
        self.assertIn("Restored Acme.", page)
        self.assertEqual([c.name for c in companies_for(self.user)], ["Acme"])
        self.assertEqual([j.title for j in jobs_for(self.user)], ["Backend Engineer"])

    def test_undo_restores_a_job_and_returns_to_the_jobs_page(self):
        _ = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        response = self.client.post(reverse("tracker:undo_delete"))
        self.assertRedirects(response, reverse("tracker:jobs"))
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_deleted)

    def test_undo_restores_a_skill(self):
        python = Skill.objects.create(name="Python")
        _ = self.client.post(reverse("tracker:skill_delete", args=[python.id]))
        response = self.client.post(reverse("tracker:undo_delete"))
        self.assertRedirects(response, reverse("tracker:skills"))
        self.assertEqual([s.name for s in active_skills()], ["Python"])

    def test_undo_works_once(self):
        _ = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        _ = self.undo()
        page = self.undo()
        self.assertIn("There&#x27;s nothing to undo.", page)

    def test_only_the_latest_delete_can_be_undone(self):
        other = Job.objects.create(company=self.acme, title="Data Engineer")
        _ = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        _ = self.client.post(reverse("tracker:job_delete", args=[other.id]))
        _ = self.undo()
        self.assertEqual([j.title for j in jobs_for(self.user)], ["Data Engineer"])

    def test_undo_message_disappears_after_undoing(self):
        _ = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        page = self.undo()
        self.assertNotIn(f'action="{reverse("tracker:undo_delete")}"', page)

    def test_cannot_restore_over_a_company_with_the_same_name(self):
        _ = self.client.post(reverse("tracker:company_delete", args=[self.acme.id]))
        _ = Company.objects.create(user_owner=self.user, name="ACME")
        page = self.undo()
        self.assertIn("Couldn&#x27;t restore Acme", page)
        self.acme.refresh_from_db()
        self.assertTrue(self.acme.is_deleted)

    def test_cannot_restore_over_a_skill_with_the_same_name(self):
        python = Skill.objects.create(name="Python")
        _ = self.client.post(reverse("tracker:skill_delete", args=[python.id]))
        _ = Skill.objects.create(name="python")
        page = self.undo()
        self.assertIn("Couldn&#x27;t restore Python", page)
        python.refresh_from_db()
        self.assertTrue(python.is_deleted)

    def test_record_already_restored_elsewhere(self):
        _ = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        _ = Job.objects.filter(id=self.job.id).update(
            is_deleted=False
        )  # e.g. in the admin
        page = self.undo()
        self.assertIn("no longer deleted", page)

    def test_undo_requires_post_and_login(self):
        url = reverse("tracker:undo_delete")
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.assertRedirects(
            self.client.post(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_another_users_session_cannot_undo_my_delete(self):
        _ = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        self.client.force_login(User.objects.create_user("bob@example.com", "x"))
        page = self.undo()  # a new login gets a fresh session: nothing to undo
        self.assertIn("nothing to undo", page)
        self.job.refresh_from_db()
        self.assertTrue(self.job.is_deleted)

    def test_only_the_latest_deletes_message_offers_undo(self):
        other = Job.objects.create(company=self.acme, title="Data Engineer")
        _ = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        response = self.client.post(
            reverse("tracker:job_delete", args=[other.id]), follow=True
        )
        page = response.content.decode()
        # Both messages show, but only the latest delete's has an Undo button.
        self.assertIn("Deleted Backend Engineer.", page)
        self.assertIn("Deleted Data Engineer.", page)
        self.assertEqual(page.count(f'action="{reverse("tracker:undo_delete")}"'), 1)
        first = page.index("Deleted Backend Engineer.")
        second = page.index("Deleted Data Engineer.")
        undo = page.index(f'action="{reverse("tracker:undo_delete")}"')
        self.assertLess(second, undo)
        self.assertLess(first, second)
