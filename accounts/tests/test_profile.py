"""The profile page."""

from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse

from ..models import User


class ProfilePageTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(
            "ada@example.com",
            "x",
            first_name="Ada",
            last_name="Lovelace",
            phone_number="+1 (555) 123-4567",
        )

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def post(self, **changes: str) -> str:
        """Submit the form with the current values, overridden by `changes`."""
        data = {
            "first_name": "Ada",
            "middle_name": "",
            "last_name": "Lovelace",
            "preferred_name": "",
            "phone_number": "+1 (555) 123-4567",
            **changes,
        }
        response = self.client.post(reverse("accounts:profile"), data, follow=True)
        return response.content.decode()

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("accounts:profile"))
        self.assertRedirects(
            response, f"{reverse('tracker:login')}?next={reverse('accounts:profile')}"
        )

    def test_shows_current_details_and_email(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, 'value="Lovelace"')
        self.assertContains(response, "ada@example.com")
        self.assertContains(response, 'type="tel"')
        self.assertContains(response, 'aria-current="page"')  # sidebar link is active

    def test_saves_changes_and_normalizes_the_phone_number(self):
        page = self.post(
            middle_name="King", preferred_name="Countess", phone_number="1 555 867 5309"
        )
        self.assertIn("Your profile has been updated.", page)
        self.user.refresh_from_db()
        self.assertEqual(self.user.get_full_name(), "Ada King Lovelace")
        self.assertEqual(self.user.get_short_name(), "Countess")
        self.assertEqual(self.user.phone_number, "+1 (555) 867-5309")

    def test_redirects_after_saving(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "phone_number": "+1 555 123 4567",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))

    def test_invalid_phone_number_is_rejected(self):
        page = self.post(phone_number="555-0100")
        self.assertIn("Enter a phone number with its country code", page)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone_number, "+1 (555) 123-4567")

    def test_required_names_cannot_be_blank(self):
        page = self.post(first_name="")
        self.assertIn("This field is required.", page)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Ada")

    def test_email_cannot_be_changed_here(self):
        _ = self.post(email="attacker@example.com", is_staff="on", is_superuser="on")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ada@example.com")
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
