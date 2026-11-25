"""The user admin."""

from typing import ClassVar, cast, override

from django.test import TestCase
from django.urls import reverse

from ..models import User


def user_pk(user: User) -> str:
    """The user's primary key as a string (django-types leaves pk untyped)."""
    return str(cast(object, user.pk))


class UserAdminTests(TestCase):
    admin_user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.admin_user = User.objects.create_superuser("root@example.com", "x")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.admin_user)

    def test_change_page_shows_the_new_fields(self):
        response = self.client.get(
            reverse("admin:accounts_user_change", args=[user_pk(self.admin_user)])
        )
        self.assertContains(response, "Middle name")
        self.assertContains(response, "Preferred name")
        self.assertContains(response, "Phone number")
        self.assertNotContains(response, 'name="username"')

    def test_list_and_search(self):
        response = self.client.get(
            reverse("admin:accounts_user_changelist"), {"q": "root"}
        )
        self.assertContains(response, "root@example.com")

    def test_add_user_normalizes_email_and_phone(self):
        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "email": "Grace@Example.com",
                "first_name": "Grace",
                "middle_name": "Brewster",
                "last_name": "Hopper",
                "preferred_name": "Amazing Grace",
                "phone_number": "1-555-867-5309",
                "password1": "a-long-unusual-password-42",
                "password2": "a-long-unusual-password-42",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="grace@example.com")
        self.assertEqual(user.phone_number, "+1 (555) 867-5309")
        self.assertEqual(user.get_full_name(), "Grace Brewster Hopper")
        self.assertEqual(user.preferred_name, "Amazing Grace")
        self.assertTrue(user.check_password("a-long-unusual-password-42"))
