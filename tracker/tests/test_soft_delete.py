"""Soft deletes: the delete buttons mark records is_deleted, which hides them."""

from typing import ClassVar, override

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from ..charts import status_counts
from ..models import Application, Company, Job, Skill
from ..ownership import active_skills, companies_for, jobs_for


class CompanySoftDeleteTests(TestCase):
    user: ClassVar[User]
    acme: ClassVar[Company]
    job: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        cls.job = Job.objects.create(company=cls.acme, title="Backend Engineer")
        _ = Application.objects.create(job=cls.job)

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def delete(self) -> str:
        url = reverse("tracker:company_delete", args=[self.acme.id])
        return self.client.post(url, follow=True).content.decode()

    def test_edit_page_has_a_confirmed_delete_button_and_add_page_does_not(self):
        page = self.client.get(reverse("tracker:company_edit", args=[self.acme.id]))
        self.assertContains(
            page, reverse("tracker:company_delete", args=[self.acme.id])
        )
        self.assertContains(page, 'data-confirm="Delete Acme?')
        self.assertContains(page, "Delete company")
        self.assertNotContains(
            self.client.get(reverse("tracker:company_add")), "Delete company"
        )

    def test_delete_marks_the_company_deleted_and_returns_to_the_list(self):
        page = self.delete()
        self.assertIn("Deleted Acme.", page)
        self.acme.refresh_from_db()
        self.assertTrue(self.acme.is_deleted)  # still in the database

    def test_deleted_company_and_its_jobs_are_hidden(self):
        _ = self.delete()
        self.assertEqual(list(companies_for(self.user)), [])
        self.assertEqual(list(jobs_for(self.user)), [])  # hidden with its company
        self.assertEqual(status_counts(self.user).totals[-1], 0)
        jobs_page = self.client.get(reverse("tracker:jobs"))
        self.assertNotContains(jobs_page, "Backend Engineer")
        edit = self.client.get(reverse("tracker:company_edit", args=[self.acme.id]))
        self.assertEqual(edit.status_code, 404)

    def test_a_deleted_companys_name_can_be_used_again(self):
        _ = self.delete()
        response = self.client.post(reverse("tracker:company_add"), {"name": "acme"})
        self.assertRedirects(response, reverse("tracker:companies"))
        self.assertEqual(companies_for(self.user).get().name, "acme")

    def test_only_active_names_must_be_unique_in_the_database(self):
        _ = self.delete()
        _ = Company.objects.create(user_owner=self.user, name="ACME")  # allowed
        with self.assertRaises(IntegrityError), transaction.atomic():
            _ = Company.objects.create(user_owner=self.user, name="Acme")

    def test_delete_requires_post_login_and_ownership(self):
        url = reverse("tracker:company_delete", args=[self.acme.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(User.objects.create_user("bob@example.com", "x"))
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.logout()
        self.assertRedirects(
            self.client.post(url), f"{reverse('tracker:login')}?next={url}"
        )
        self.acme.refresh_from_db()
        self.assertFalse(self.acme.is_deleted)

    def test_superusers_still_see_deleted_companies_in_the_admin(self):
        _ = self.delete()
        self.client.force_login(User.objects.create_superuser("root@example.com", "x"))
        page = self.client.get(
            reverse("admin:tracker_company_changelist"), {"is_deleted__exact": "1"}
        )
        self.assertContains(page, "Acme")


class JobSoftDeleteTests(TestCase):
    user: ClassVar[User]
    acme: ClassVar[Company]
    job: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")
        cls.acme = Company.objects.create(user_owner=cls.user, name="Acme")
        cls.job = Job.objects.create(company=cls.acme, title="Backend Engineer")
        _ = Application.objects.create(job=cls.job)
        _ = Job.objects.create(company=cls.acme, title="Data Engineer")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_edit_page_has_a_confirmed_delete_button(self):
        page = self.client.get(reverse("tracker:job_edit", args=[self.job.id]))
        self.assertContains(page, 'data-confirm="Delete Backend Engineer?')
        self.assertNotContains(
            self.client.get(reverse("tracker:job_add")), "Delete job"
        )

    def test_delete_hides_the_job_and_its_applications(self):
        response = self.client.post(
            reverse("tracker:job_delete", args=[self.job.id]), follow=True
        )
        self.assertRedirects(response, reverse("tracker:jobs"))
        self.assertContains(response, "Deleted Backend Engineer.")
        self.job.refresh_from_db()
        self.assertTrue(self.job.is_deleted)
        self.assertEqual([j.title for j in jobs_for(self.user)], ["Data Engineer"])
        self.assertEqual(
            status_counts(self.user).totals[-1], 0
        )  # its application is hidden
        self.assertEqual(
            self.client.get(
                reverse("tracker:job_edit", args=[self.job.id])
            ).status_code,
            404,
        )

    def test_companies_page_counts_only_active_jobs(self):
        _ = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        response = self.client.get(reverse("tracker:companies"))
        # Acme's Jobs column shows 1: the deleted job isn't counted.
        self.assertContains(response, 'tabular-nums">1</td>')
        self.assertNotContains(response, 'tabular-nums">2</td>')

    def test_another_users_job_cannot_be_deleted(self):
        self.client.force_login(User.objects.create_user("bob@example.com", "x"))
        response = self.client.post(reverse("tracker:job_delete", args=[self.job.id]))
        self.assertEqual(response.status_code, 404)
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_deleted)


class SkillSoftDeleteTests(TestCase):
    staff: ClassVar[User]
    python: ClassVar[Skill]
    docker: ClassVar[Skill]
    job: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.staff = User.objects.create_user("staff@example.com", "x", is_staff=True)
        cls.python = Skill.objects.create(name="Python")
        cls.docker = Skill.objects.create(name="Docker")
        company = Company.objects.create(user_owner=cls.staff, name="Acme")
        cls.job = Job.objects.create(company=company, title="Backend Engineer")
        cls.job.skills.set([cls.python, cls.docker])

    @override
    def setUp(self) -> None:
        self.client.force_login(self.staff)

    def delete_python(self) -> None:
        _ = self.client.post(reverse("tracker:skill_delete", args=[self.python.id]))

    def test_edit_page_has_a_confirmed_delete_button(self):
        page = self.client.get(reverse("tracker:skill_edit", args=[self.python.id]))
        self.assertContains(page, 'data-confirm="Delete Python?')
        self.assertNotContains(
            self.client.get(reverse("tracker:skill_add")), "Delete skill"
        )

    def test_delete_hides_the_skill_from_the_list_and_job_forms(self):
        response = self.client.post(
            reverse("tracker:skill_delete", args=[self.python.id]), follow=True
        )
        self.assertRedirects(response, reverse("tracker:skills"))
        self.assertContains(response, "Deleted Python.")
        self.assertEqual([s.name for s in active_skills()], ["Docker"])
        job_form = self.client.get(reverse("tracker:job_edit", args=[self.job.id]))
        self.assertNotContains(job_form, f'value="{self.python.id}"')
        self.assertContains(job_form, f'value="{self.docker.id}" selected')

    def test_saving_a_job_drops_its_deleted_skills(self):
        self.delete_python()
        _ = self.client.post(
            reverse("tracker:job_edit", args=[self.job.id]),
            {
                "company": str(self.job.company.id),
                "title": "Backend Engineer",
                "skills": [str(self.docker.id)],
            },
        )
        self.assertEqual(list(self.job.skills.all()), [self.docker])

    def test_a_deleted_skills_name_can_be_used_again(self):
        self.delete_python()
        response = self.client.post(reverse("tracker:skill_add"), {"name": "python"})
        self.assertRedirects(response, reverse("tracker:skills"))
        self.assertEqual(Skill.objects.filter(name__iexact="python").count(), 2)

    def test_only_staff_can_delete_skills(self):
        self.client.force_login(User.objects.create_user("ada@example.com", "x"))
        response = self.client.post(
            reverse("tracker:skill_delete", args=[self.python.id])
        )
        self.assertEqual(response.status_code, 403)
        self.python.refresh_from_db()
        self.assertFalse(self.python.is_deleted)

    def test_deleted_skill_edit_page_is_a_404(self):
        self.delete_python()
        url = reverse("tracker:skill_edit", args=[self.python.id])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_skill_soft_delete_keeps_the_record(self):
        self.delete_python()
        self.python.refresh_from_db()
        self.assertTrue(self.python.is_deleted)
        # The link remains in the database; only the skill is hidden.
        self.assertTrue(self.job.skills.filter(id=self.python.id).exists())


class DeleteButtonPlacementTests(TestCase):
    def test_delete_button_sits_in_the_edit_forms_button_row(self):
        staff = User.objects.create_user("staff@example.com", "x", is_staff=True)
        company = Company.objects.create(user_owner=staff, name="Acme")
        job = Job.objects.create(company=company, title="Backend Engineer")
        skill = Skill.objects.create(name="Python")
        self.client.force_login(staff)
        for url, delete_url in [
            (
                reverse("tracker:company_edit", args=[company.id]),
                reverse("tracker:company_delete", args=[company.id]),
            ),
            (
                reverse("tracker:job_edit", args=[job.id]),
                reverse("tracker:job_delete", args=[job.id]),
            ),
            (
                reverse("tracker:skill_edit", args=[skill.id]),
                reverse("tracker:skill_delete", args=[skill.id]),
            ),
        ]:
            with self.subTest(url):
                page = self.client.get(url).content.decode()
                cancel = page.index(">Cancel</a>")
                button = page.index('form="delete-form"')
                edit_form_end = page.index("</form>", cancel)
                # The button follows Cancel inside the edit form...
                self.assertLess(cancel, button)
                self.assertLess(button, edit_form_end)
                self.assertIn("ml-auto", page[button : button + 200])
                # ...and submits the separate delete form, which has the confirmation.
                delete_form = page[page.index('<form id="delete-form"') :][:400]
                self.assertIn(f'action="{delete_url}"', delete_form)
                self.assertIn("data-confirm=", delete_form)
