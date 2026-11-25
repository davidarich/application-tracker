"""Managing API access (OAuth 2.0 refresh token grants) on the API tokens page."""

from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse

from ..api_tokens import RefreshError, issue_grant, refresh_tokens
from ..models import ApiGrant, ApiToken, User

PAGE = reverse("accounts:api_tokens")
PROFILE = reverse("accounts:profile")
CREATE = reverse("accounts:api_token_create")


def revoke_url(grant: ApiGrant) -> str:
    return reverse("accounts:api_token_revoke", args=[grant.id])


def works(refresh_token: str) -> bool:
    """Whether the refresh token can still be exchanged (which uses it up)."""
    try:
        _ = refresh_tokens(refresh_token)
    except RefreshError:
        return False
    return True


class ApiTokenPageTests(TestCase):
    user: ClassVar[User]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_the_api_tokens_page(self):
        page = self.client.get(PAGE).content.decode()
        self.assertIn("<title>API tokens · Job Tracker</title>", page)
        self.assertIn('id="api-tokens"', page)
        self.assertIn("You don't have any API tokens.", page)
        self.assertIn(f'action="{CREATE}"', page)
        self.assertIn('href="/api/v1/docs"', page)
        self.assertIn("OAuth 2.0", page)

    def test_it_is_listed_under_account_in_the_sidebar(self):
        page = self.client.get(PAGE).content.decode()
        account = page[page.index(">Account</p>") : page.index('action="/logout/"')]
        link = account[account.index(f'href="{PAGE}"') :].split("</a>", 1)[0]
        self.assertIn('aria-current="page"', link)
        self.assertIn("API tokens", link)
        # Listed on other pages too, without being the current one.
        profile = self.client.get(PROFILE).content.decode()
        link = profile[profile.index(f'href="{PAGE}"') :].split("</a>", 1)[0]
        self.assertNotIn('aria-current="page"', link)

    def test_the_profile_page_no_longer_has_the_tokens(self):
        _ = issue_grant(self.user, "Script")
        page = self.client.get(PROFILE).content.decode()
        self.assertNotIn('id="api-tokens"', page)
        self.assertNotIn("Script", page)
        self.assertNotIn(f'action="{CREATE}"', page)

    def test_logging_in_is_required(self):
        self.client.logout()
        response = self.client.get(PAGE)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_a_new_refresh_token_is_shown_once_and_works(self):
        response = self.client.post(CREATE, {"name": " Browser extension "})
        # Not following the redirect: that would use up the one showing.
        self.assertRedirects(response, PAGE, fetch_redirect_response=False)
        grant = ApiGrant.objects.get(user=self.user)
        self.assertEqual(grant.name, "Browser extension")
        shown = self.client.get(PAGE)
        # Not cached by the browser, as it holds the refresh token.
        self.assertIn("no-store", shown["Cache-Control"])
        page = shown.content.decode()
        start = page.index("Your new refresh token for Browser extension")
        token = page[start:].split('select-all">', 1)[1].split("<", 1)[0]
        self.assertTrue(token.startswith("rt_"))
        self.assertIn("/api/v1/oauth/token", page[start:])
        self.assertTrue(works(token))
        again = self.client.get(PAGE).content.decode()
        self.assertNotIn(token, again)
        self.assertIn("Browser extension", again)
        self.assertIn("Last used", again)  # by the exchange above

    def test_unused_grants_say_so(self):
        _ = issue_grant(self.user, "Script")
        self.assertContains(self.client.get(PAGE), "Never used")

    def test_a_name_is_required(self):
        response = self.client.post(CREATE, {"name": "  "}, follow=True)
        self.assertContains(response, "Give the token a name, e.g. Browser extension.")
        self.assertFalse(ApiGrant.objects.exists())

    def test_revoking_ends_all_of_the_grants_tokens(self):
        grant, refresh_token = issue_grant(self.user, "Script")
        pair = refresh_tokens(refresh_token)
        response = self.client.post(revoke_url(grant), follow=True)
        self.assertContains(response, "Revoked the token Script.")
        self.assertContains(response, "You don't have any API tokens.")
        self.assertFalse(works(pair.refresh_token))
        self.assertFalse(ApiToken.objects.filter(grant=grant).exists())
        grant.refresh_from_db()
        self.assertIsNotNone(grant.revoked_at)

    def test_other_users_grants_cannot_be_revoked(self):
        other = User.objects.create_user("bob@example.com", "x")
        grant, token = issue_grant(other, "Bob's")
        self.assertEqual(self.client.post(revoke_url(grant)).status_code, 404)
        self.assertTrue(works(token))
        self.assertNotIn("Bob's", self.client.get(PAGE).content.decode())

    def test_grants_are_created_and_revoked_only_by_post(self):
        grant, _token = issue_grant(self.user, "Script")
        self.assertEqual(self.client.get(CREATE).status_code, 405)
        self.assertEqual(self.client.get(revoke_url(grant)).status_code, 405)


class ApiGrantAdminTests(TestCase):
    def test_grants_can_be_revoked_in_the_admin_but_not_added(self):
        root = User.objects.create_superuser("root@example.com", "x")
        self.client.force_login(root)
        grant, token = issue_grant(root, "Script")
        changelist = reverse("admin:accounts_apigrant_changelist")
        page = self.client.get(changelist).content.decode()
        self.assertIn("Script", page)
        self.assertNotIn(reverse("admin:accounts_apigrant_add"), page)
        detail = self.client.get(
            reverse("admin:accounts_apigrant_change", args=[grant.id])
        )
        self.assertContains(detail, token[:12])  # the token's prefix, never the token
        self.assertNotContains(detail, token)
        response = self.client.post(
            changelist,
            {"action": "revoke", "_selected_action": [str(grant.id)]},
            follow=True,
        )
        self.assertContains(response, "Revoked 1 grant.")
        self.assertFalse(works(token))
