"""Skills: shared by all users, and linked to jobs."""

from collections.abc import Sequence
from typing import ClassVar, cast, override

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from ..models import Company, Job, Skill


class SkillModelTests(TestCase):
    def test_names_are_unique_ignoring_case(self):
        _ = Skill.objects.create(name="Python")
        with self.assertRaises(IntegrityError):
            _ = Skill.objects.create(name="python")

    def test_description_is_optional_and_skills_sort_by_name(self):
        _ = Skill.objects.create(
            name="SQL", description="Querying relational databases."
        )
        _ = Skill.objects.create(name="Kubernetes")
        self.assertEqual(
            [str(skill) for skill in Skill.objects.all()], ["Kubernetes", "SQL"]
        )
        self.assertEqual(Skill.objects.get(name="Kubernetes").description, "")


class JobSkillsTests(TestCase):
    python: ClassVar[Skill]
    sql: ClassVar[Skill]
    job: ClassVar[Job]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.python = Skill.objects.create(name="Python")
        cls.sql = Skill.objects.create(name="SQL")
        user = User.objects.create_user("ada@example.com", "x")
        company = Company.objects.create(user_owner=user, name="Acme")
        cls.job = Job.objects.create(company=company, title="Backend Engineer")

    def test_a_job_can_have_many_skills_and_none_by_default(self):
        self.assertEqual(list(self.job.skills.all()), [])
        self.job.skills.add(self.python, self.sql)
        self.assertEqual(list(self.job.skills.all()), [self.python, self.sql])

    def test_skills_are_shared_between_users(self):
        other = User.objects.create_user("bob@example.com", "x")
        other_job = Job.objects.create(
            company=Company.objects.create(user_owner=other, name="Globex"),
            title="Data Engineer",
        )
        self.job.skills.add(self.python)
        other_job.skills.add(self.python)
        self.assertEqual(
            set(Job.objects.filter(skills=self.python)), {self.job, other_job}
        )

    def test_deleting_a_job_keeps_its_skills_and_deleting_a_skill_keeps_jobs(self):
        self.job.skills.add(self.python, self.sql)
        _ = self.sql.delete()
        self.assertEqual(list(self.job.skills.all()), [self.python])
        _ = self.job.delete()
        self.assertTrue(Skill.objects.filter(name="Python").exists())


class SkillAdminTests(TestCase):
    @override
    def setUp(self) -> None:
        self.client.force_login(User.objects.create_superuser("root@example.com", "x"))

    def test_skills_can_be_added_and_searched_in_the_admin(self):
        response = self.client.post(
            reverse("admin:tracker_skill_add"),
            {"name": "Rust", "description": "Systems programming."},
        )
        self.assertEqual(response.status_code, 302)
        page = self.client.get(reverse("admin:tracker_skill_changelist"), {"q": "rust"})
        self.assertContains(page, "Systems programming.")

    def test_job_admin_offers_skills(self):
        response = self.client.get(reverse("admin:tracker_job_add"))
        self.assertContains(response, 'name="skills"')


class AdminSidebarTests(TestCase):
    def page(self, user: User) -> str:
        self.client.force_login(user)
        return self.client.get(reverse("tracker:jobs")).content.decode()

    def test_staff_see_an_admin_section_with_skills_and_django_admin(self):
        page = self.page(
            User.objects.create_user("staff@example.com", "x", is_staff=True)
        )
        admin_section = page[page.index(">Admin</p>") :]
        admin_section = admin_section[: admin_section.index(">Account</p>")]
        self.assertIn(f'href="{reverse("tracker:skills")}"', admin_section)
        self.assertIn(f'href="{reverse("admin:index")}"', admin_section)
        self.assertIn("Django admin", admin_section)

    def test_other_users_see_no_admin_section(self):
        page = self.page(User.objects.create_user("ada@example.com", "x"))
        self.assertNotIn(">Admin</p>", page)
        self.assertNotIn(reverse("tracker:skills"), page)
        self.assertNotIn(reverse("admin:index"), page)


class SkillPagesTests(TestCase):
    staff: ClassVar[User]
    python: ClassVar[Skill]
    docker: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.staff = User.objects.create_user("staff@example.com", "x", is_staff=True)
        cls.python = Skill.objects.create(
            name="Python", description="A popular language."
        )
        cls.docker = Skill.objects.create(name="Docker", description="Containers.")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.staff)

    def names(self, **params: str) -> list[str]:
        response = self.client.get(reverse("tracker:skills"), params)
        return [s.name for s in cast(Sequence[Skill], response.context["skills"])]

    def test_pages_are_staff_only(self):
        self.client.force_login(User.objects.create_user("ada@example.com", "x"))
        for url in (
            reverse("tracker:skills"),
            reverse("tracker:skill_add"),
            reverse("tracker:skill_edit", args=[self.python.id]),
        ):
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.post(reverse("tracker:skill_add"), {"name": "Sneaky"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Skill.objects.filter(name="Sneaky").exists())

    def test_requires_login(self):
        self.client.logout()
        url = reverse("tracker:skills")
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_lists_skills_by_name_with_links_and_an_add_button(self):
        self.assertEqual(self.names(), ["Docker", "Python"])
        page = self.client.get(reverse("tracker:skills")).content.decode()
        self.assertIn(
            f'href="{reverse("tracker:skill_edit", args=[self.python.id])}"', page
        )
        self.assertIn(f'href="{reverse("tracker:skill_add")}"', page)
        self.assertIn("A popular language.", page)
        self.assertIn("2 skills", page)

    def test_search_matches_names_and_descriptions(self):
        self.assertEqual(self.names(q="pyth"), ["Python"])
        self.assertEqual(self.names(q="container"), ["Docker"])

    def test_paging(self):
        _ = Skill.objects.bulk_create(Skill(name=f"Skill {n:02}") for n in range(30))
        self.assertEqual(len(self.names()), 25)
        self.assertEqual(len(self.names(page="2")), 7)

    def test_add_a_skill(self):
        response = self.client.post(
            reverse("tracker:skill_add"),
            {"name": "  Rust  ", "description": "Systems programming."},
            follow=True,
        )
        self.assertRedirects(response, reverse("tracker:skills"))
        self.assertContains(response, "Added Rust.")
        self.assertEqual(
            Skill.objects.get(name="Rust").description, "Systems programming."
        )

    def test_rejects_a_duplicate_name_ignoring_case(self):
        response = self.client.post(reverse("tracker:skill_add"), {"name": "PYTHON"})
        self.assertContains(response, "A skill with this name already exists.", count=1)
        self.assertEqual(Skill.objects.filter(name__iexact="python").count(), 1)

    def test_edit_a_skill(self):
        url = reverse("tracker:skill_edit", args=[self.python.id])
        page = self.client.get(url)
        self.assertContains(page, "Edit Python")
        self.assertContains(page, "A popular language.")
        response = self.client.post(
            url, {"name": "Python 3", "description": "The current Python."}, follow=True
        )
        self.assertRedirects(response, reverse("tracker:skills"))
        self.assertContains(response, "Saved Python 3.")
        self.python.refresh_from_db()
        self.assertEqual(self.python.name, "Python 3")

    def test_edit_keeps_its_own_name_but_rejects_another_skills_name(self):
        url = reverse("tracker:skill_edit", args=[self.python.id])
        _ = self.client.post(url, {"name": "python", "description": ""})
        self.python.refresh_from_db()
        self.assertEqual(self.python.name, "python")  # changing case is fine
        response = self.client.post(url, {"name": "docker", "description": ""})
        self.assertContains(response, "A skill with this name already exists.")
        self.assertContains(response, "Edit python")  # heading keeps the saved name

    def test_sidebar_skills_link_is_active_on_skill_pages(self):
        for url in (reverse("tracker:skills"), reverse("tracker:skill_add")):
            with self.subTest(url):
                page = self.client.get(url).content.decode()
                link = page[page.index(f'href="{reverse("tracker:skills")}"') :][:400]
                self.assertIn("ring-white/6", link)

    def test_list_sorts_names_ignoring_case(self):
        _ = Skill.objects.create(name="AWS Lambda")
        _ = Skill.objects.create(name="Amazon S3")
        self.assertEqual(self.names(), ["Amazon S3", "AWS Lambda", "Docker", "Python"])
