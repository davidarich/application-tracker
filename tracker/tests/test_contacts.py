"""Adding, editing and deleting contacts (from a company's page)."""

from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from ..models import Company, Contact
from .helpers import owner


class ContactPagesTests(TestCase):
    acme: ClassVar[Company]
    zoe: ClassVar[Contact]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.acme = Company.objects.create(user_owner=owner(), name="Acme")
        cls.zoe = Contact.objects.create(
            company=cls.acme, name="Zoe", email="zoe@acme.example"
        )

    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def add_url(self, company: Company | None = None) -> str:
        return reverse("tracker:contact_add", args=[(company or self.acme).id])

    def edit_url(self, contact: Contact | None = None) -> str:
        return reverse("tracker:contact_edit", args=[(contact or self.zoe).id])

    def delete_url(self, contact: Contact | None = None) -> str:
        return reverse("tracker:contact_delete", args=[(contact or self.zoe).id])

    def contacts_url(self) -> str:
        return f"{reverse('tracker:company_detail', args=[self.acme.id])}#contacts"

    def test_company_page_links_to_add_and_edit(self):
        page = self.client.get(
            reverse("tracker:company_detail", args=[self.acme.id])
        ).content.decode()
        self.assertIn(f'href="{self.add_url()}"', page)
        self.assertIn(f'href="{self.edit_url()}"', page)

    def test_requires_login(self):
        self.client.logout()
        for url in (self.add_url(), self.edit_url()):
            self.assertRedirects(
                self.client.get(url), f"{reverse('tracker:login')}?next={url}"
            )

    def test_add_a_contact(self):
        page = self.client.get(self.add_url()).content.decode()
        self.assertIn("Add a contact at Acme", page)
        self.assertIn('ring-white/6">', page)  # Companies nav stays active
        response = self.client.post(
            self.add_url(),
            {
                "name": "Sam Hiring",
                "email": "sam@acme.example",
                "phone_number": "+1 512-555-0100",
                "linkedin_url": "https://www.linkedin.com/in/sam",
            },
        )
        self.assertRedirects(
            response, self.contacts_url(), fetch_redirect_response=False
        )
        sam = Contact.objects.get(name="Sam Hiring")
        self.assertEqual(sam.company, self.acme)
        self.assertEqual(sam.linkedin_url, "https://www.linkedin.com/in/sam")

    def test_name_is_required_and_email_and_link_are_checked(self):
        response = self.client.post(
            self.add_url(), {"name": "", "email": "nope", "linkedin_url": "nope"}
        )
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn("This field is required.", page)
        self.assertIn("Enter a valid email address.", page)
        self.assertIn("Enter a valid URL.", page)
        self.assertEqual(Contact.objects.count(), 1)

    def test_edit_a_contact(self):
        page = self.client.get(self.edit_url()).content.decode()
        self.assertIn('value="Zoe"', page)
        self.assertIn(f'href="{self.contacts_url()}"', page)  # Cancel
        self.assertIn('id="delete-form"', page)
        response = self.client.post(self.edit_url(), {"name": "Zoe Smith", "email": ""})
        self.assertRedirects(
            response, self.contacts_url(), fetch_redirect_response=False
        )
        self.zoe.refresh_from_db()
        self.assertEqual((self.zoe.name, self.zoe.email), ("Zoe Smith", ""))
        self.assertEqual(self.zoe.company, self.acme)

    def test_delete_a_contact(self):
        self.assertEqual(self.client.get(self.delete_url()).status_code, 405)
        response = self.client.post(self.delete_url(), follow=True)
        self.assertRedirects(response, self.contacts_url())
        self.assertContains(response, "Deleted Zoe.")
        self.assertFalse(Contact.objects.exists())

    def test_other_users_companies_and_contacts_are_404(self):
        bob = User.objects.create_user("bob@example.com", "x")
        bobs = Company.objects.create(user_owner=bob, name="Bob Co")
        theirs = Contact.objects.create(company=bobs, name="Theirs")
        self.assertEqual(self.client.get(self.add_url(bobs)).status_code, 404)
        self.assertEqual(
            self.client.post(self.add_url(bobs), {"name": "X"}).status_code, 404
        )
        self.assertEqual(self.client.get(self.edit_url(theirs)).status_code, 404)
        self.assertEqual(
            self.client.post(self.edit_url(theirs), {"name": "X"}).status_code, 404
        )
        self.assertEqual(self.client.post(self.delete_url(theirs)).status_code, 404)
        self.assertTrue(Contact.objects.filter(id=theirs.id, name="Theirs").exists())

    def test_contacts_of_deleted_companies_are_404(self):
        _ = Company.objects.filter(id=self.acme.id).update(is_deleted=True)
        self.assertEqual(self.client.get(self.add_url()).status_code, 404)
        self.assertEqual(self.client.get(self.edit_url()).status_code, 404)
