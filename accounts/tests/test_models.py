"""The user model: creation, email handling and names."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from ..models import User


class UserModelTests(TestCase):
    def make_user(
        self, phone_number: str = "+1 555 123 4567", middle_name: str = ""
    ) -> User:
        return User(
            email="Ada@Example.com",
            first_name="Ada",
            middle_name=middle_name,
            last_name="Lovelace",
            phone_number=phone_number,
        )

    def test_create_user_lowercases_the_email_and_hashes_the_password(self):
        user = User.objects.create_user("Ada@Example.COM", "s3cret-pass-123")
        self.assertEqual(user.email, "ada@example.com")
        self.assertTrue(user.check_password("s3cret-pass-123"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_requires_an_email(self):
        with self.assertRaises(ValueError):
            _ = User.objects.create_user("", "x")

    def test_create_superuser_sets_admin_flags(self):
        user = User.objects.create_superuser("root@example.com", "x")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_emails_are_unique_ignoring_case(self):
        _ = User.objects.create_user("ada@example.com", "x")
        with self.assertRaises(IntegrityError):
            _ = User.objects.create_user("ADA@example.com", "x")

    def test_lookup_by_email_ignores_case(self):
        user = User.objects.create_user("ada@example.com", "x")
        self.assertEqual(User.objects.get_by_natural_key("ADA@Example.com"), user)

    def test_full_clean_normalizes_email_and_phone_number(self):
        user = self.make_user("1 555 123 4567")
        user.set_unusable_password()
        user.full_clean()
        self.assertEqual(user.email, "ada@example.com")
        self.assertEqual(user.phone_number, "+1 (555) 123-4567")

    def test_rejects_a_phone_number_without_a_country_code(self):
        user = self.make_user("555-123-4567")
        user.set_unusable_password()
        with self.assertRaises(ValidationError) as caught:
            user.full_clean()
        self.assertEqual(set(caught.exception.message_dict), {"phone_number"})

    def test_names_and_phone_are_required_but_middle_name_is_optional(self):
        user = User(email="blank@example.com")
        user.set_unusable_password()
        with self.assertRaises(ValidationError) as caught:
            user.full_clean()
        self.assertEqual(
            set(caught.exception.message_dict),
            {"first_name", "last_name", "phone_number"},
        )

    def test_names(self):
        self.assertEqual(self.make_user().get_full_name(), "Ada Lovelace")
        self.assertEqual(
            self.make_user(middle_name="King").get_full_name(), "Ada King Lovelace"
        )
        self.assertEqual(self.make_user().get_short_name(), "Ada")

    def test_display_name_uses_preferred_name_and_middle_initial(self):
        user = self.make_user()
        self.assertEqual(user.get_display_name(), "Ada Lovelace")
        user.middle_name = "king"
        self.assertEqual(user.get_display_name(), "Ada K. Lovelace")
        user.preferred_name = "Countess"
        self.assertEqual(user.get_display_name(), "Countess K. Lovelace")
        user.middle_name = "   "  # whitespace-only counts as no middle name
        self.assertEqual(user.get_display_name(), "Countess Lovelace")

    def test_whitespace_only_names_are_skipped_everywhere(self):
        user = self.make_user(middle_name="   ")
        self.assertEqual(user.get_full_name(), "Ada Lovelace")
        user.preferred_name = "  "
        self.assertEqual(user.get_short_name(), "Ada")
        self.assertEqual(user.get_display_name(), "Ada Lovelace")
        user.first_name, user.middle_name = " Ada ", " King "
        self.assertEqual(user.get_full_name(), "Ada King Lovelace")
        self.assertEqual(str(self.make_user()), "Ada@Example.com")

    def test_preferred_name_is_optional_and_used_as_the_short_name(self):
        user = self.make_user()
        user.set_unusable_password()
        user.full_clean()  # no error without a preferred name
        self.assertEqual(user.get_short_name(), "Ada")
        user.preferred_name = "Countess"
        self.assertEqual(user.get_short_name(), "Countess")
        self.assertEqual(user.get_full_name(), "Ada Lovelace")  # full name unchanged

    def test_dashboard_greets_by_preferred_name(self):
        user = User.objects.create_user(
            "bill@example.com", "x", first_name="William", preferred_name="Bill"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("tracker:dashboard"))
        self.assertContains(response, "Welcome back,<br>Bill")

    def test_header_shows_the_display_name(self):
        user = User.objects.create_user(
            "bill@example.com",
            "x",
            first_name="William",
            middle_name="Jefferson",
            last_name="Smith",
            preferred_name="Bill",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("tracker:dashboard"))
        self.assertContains(response, ">Bill J. Smith</p>")
        self.assertNotContains(response, "William Jefferson Smith")
