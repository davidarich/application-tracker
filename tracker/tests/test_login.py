"""Logging in and out with an email address."""

from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class LoginTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("alice@example.com", "s3cret-pass-123")

    def test_login_page_renders(self):
        response = self.client.get(reverse("tracker:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log in")

    def test_valid_login_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("tracker:login"),
            {"username": "alice@example.com", "password": "s3cret-pass-123"},
        )
        self.assertRedirects(response, reverse("tracker:dashboard"))

    def test_email_is_case_insensitive(self):
        response = self.client.post(
            reverse("tracker:login"),
            {"username": "Alice@Example.COM", "password": "s3cret-pass-123"},
        )
        self.assertRedirects(response, reverse("tracker:dashboard"))

    def test_login_form_asks_for_an_email(self):
        response = self.client.get(reverse("tracker:login"))
        self.assertContains(response, 'type="email"')
        self.assertContains(response, ">Email</label>")

    def test_login_honours_next(self):
        response = self.client.post(
            reverse("tracker:login"),
            {
                "username": "alice@example.com",
                "password": "s3cret-pass-123",
                "next": reverse("admin:index"),
            },
        )
        self.assertRedirects(
            response, reverse("admin:index"), fetch_redirect_response=False
        )

    def test_invalid_login_shows_error(self):
        response = self.client.post(
            reverse("tracker:login"),
            {"username": "alice@example.com", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a correct email and password")

    def test_logged_in_user_skips_login_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("tracker:login"))
        self.assertRedirects(response, reverse("tracker:dashboard"))

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("tracker:logout"))
        self.assertRedirects(response, reverse("tracker:login"))
        self.assertNotIn("_auth_user_id", self.client.session)
