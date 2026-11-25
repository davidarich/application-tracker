"""The skills endpoints: a shared list everyone reads and only staff change."""

from typing import ClassVar, override

from accounts.models import User
from tracker.models import Skill

from .helpers import ApiTestCase, names


class SkillApiTests(ApiTestCase):
    python: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.python = Skill.objects.create(name="Python", description="A language.")
        _ = Skill.objects.create(name="kubernetes", description="Runs containers.")
        _ = Skill.objects.create(name="Perl", is_deleted=True)

    def make_staff(self) -> None:
        _ = User.objects.filter(id=self.user.id).update(is_staff=True)

    def test_everyone_can_list_and_read_skills(self):
        page = self.ok("GET", "skills")
        self.assertEqual((page["count"], names(page)), (2, ["kubernetes", "Python"]))
        self.assertEqual(names(self.ok("GET", "skills?q=contain")), ["kubernetes"])
        self.assertEqual(
            self.ok("GET", f"skills/{self.python.id}"),
            {
                "id": str(self.python.id),
                "name": "Python",
                "description": "A language.",
                "creation_source": "manual",
            },
        )
        deleted = Skill.objects.get(name="Perl")
        self.assertEqual(self.call("GET", f"skills/{deleted.id}").status_code, 404)

    def test_only_staff_can_add_or_change_skills(self):
        for response in (
            self.call("POST", "skills", {"name": "Go"}),
            self.call("PATCH", f"skills/{self.python.id}", {"name": "Python 3"}),
        ):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.json(), {"detail": "Only staff can add or change skills."}
            )
        self.assertFalse(Skill.objects.filter(name="Go").exists())
        self.assertEqual(Skill.objects.get(id=self.python.id).name, "Python")

    def test_staff_add_skills_with_unique_names(self):
        self.make_staff()
        skill = self.ok(
            "POST", "skills", {"name": " Go ", "description": "Gophers."}, status=201
        )
        self.assertEqual((skill["name"], skill["description"]), ("Go", "Gophers."))
        self.assertEqual(
            self.errors("POST", "skills", {"name": "PYTHON"}),
            {"name": ["A skill with this name already exists."]},
        )
        # A deleted skill's name can be used again.
        _ = self.ok("POST", "skills", {"name": "Perl"}, status=201)

    def test_staff_patch_changes_only_the_fields_sent(self):
        self.make_staff()
        skill = self.ok("PATCH", f"skills/{self.python.id}", {"description": "Snakes."})
        self.assertEqual((skill["name"], skill["description"]), ("Python", "Snakes."))
        self.assertEqual(
            self.errors("PATCH", f"skills/{self.python.id}", {"name": "Kubernetes"}),
            {"name": ["A skill with this name already exists."]},
        )
