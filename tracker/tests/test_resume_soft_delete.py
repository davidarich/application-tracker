"""Soft delete, undo and restore for resume entries."""

from datetime import date
from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from ..models import Certification, Education, WorkExperience
from ..resume_import import CertificationEntry, ResumeExtraction
from ..resume_import.session import to_session
from ..resume_import_views import SESSION_KEY
from .helpers import owner

RESUME = reverse("tracker:resume")
UNDO = reverse("tracker:undo_delete")
RECENTLY_DELETED = reverse("tracker:recently_deleted")


def delete_url(section: str, pk: object) -> str:
    return reverse("tracker:resume_entry_delete", args=[section, pk])


def restore_url(section: str, pk: object) -> str:
    return reverse("tracker:resume_entry_restore", args=[section, pk])


class ResumeSoftDeleteTests(TestCase):
    user: ClassVar[User]
    job: ClassVar[WorkExperience]
    school: ClassVar[Education]
    cert: ClassVar[Certification]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()
        cls.job = WorkExperience.objects.create(
            user_owner=cls.user,
            title="Engineer",
            employer="Acme",
            start_date=date(2020, 1, 1),
        )
        cls.school = Education.objects.create(
            user_owner=cls.user, institution="State University"
        )
        cls.cert = Certification.objects.create(
            user_owner=cls.user, name="Cloud Architect"
        )

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_delete_hides_the_entry_and_offers_undo(self):
        response = self.client.post(delete_url("work", self.job.id), follow=True)
        self.assertRedirects(response, f"{RESUME}#work")
        page = response.content.decode()
        self.assertIn("Deleted Engineer at Acme.", page)
        self.assertIn(f'action="{UNDO}"', page)
        self.job.refresh_from_db()
        self.assertTrue(self.job.is_deleted)
        self.assertIsNotNone(self.job.deleted_at)
        self.assertNotIn("Engineer</a>", self.client.get(RESUME).content.decode())
        edit = reverse("tracker:resume_entry_edit", args=["work", self.job.id])
        self.assertEqual(self.client.get(edit).status_code, 404)  # like it's gone
        self.assertEqual(
            self.client.post(delete_url("work", self.job.id)).status_code, 404
        )

    def test_undo_restores_the_entry_to_its_section(self):
        for section, entry in (
            ("work", self.job),
            ("education", self.school),
            ("certifications", self.cert),
        ):
            with self.subTest(section):
                _ = self.client.post(delete_url(section, entry.id))
                response = self.client.post(UNDO)
                self.assertRedirects(
                    response, f"{RESUME}#{section}", fetch_redirect_response=False
                )
                entry.refresh_from_db()
                self.assertFalse(entry.is_deleted)
                self.assertIsNone(entry.deleted_at)

    def test_undo_only_once(self):
        _ = self.client.post(delete_url("education", self.school.id))
        _ = self.client.post(UNDO)
        response = self.client.post(UNDO, follow=True)
        self.assertContains(response, "There&#x27;s nothing to undo.")

    def test_recently_deleted_lists_entries_newest_first_and_restores_them(self):
        _ = self.client.post(delete_url("education", self.school.id))
        _ = self.client.post(delete_url("certifications", self.cert.id))
        page = self.client.get(RECENTLY_DELETED).content.decode()
        section = page[page.index('id="deleted-resume-title"') :]
        self.assertIn("2 deleted", section)
        self.assertLess(
            section.index("Cloud Architect"), section.index("State University")
        )
        self.assertIn("Certifications", section)
        self.assertIn(f'action="{restore_url("education", self.school.id)}"', section)

        response = self.client.post(
            restore_url("education", self.school.id), follow=True
        )
        self.assertRedirects(response, RECENTLY_DELETED)
        self.assertContains(response, "Restored State University to your resume.")
        self.school.refresh_from_db()
        self.assertFalse(self.school.is_deleted)
        self.assertIn("State University", self.client.get(RESUME).content.decode())

    def test_no_deleted_entries(self):
        self.assertContains(
            self.client.get(RECENTLY_DELETED), "No deleted resume entries."
        )

    def test_restoring_requires_a_deleted_entry_of_your_own_in_that_section(self):
        self.assertEqual(
            self.client.post(restore_url("work", self.job.id)).status_code, 404
        )  # not deleted
        _ = self.client.post(delete_url("work", self.job.id))
        self.assertEqual(
            self.client.post(restore_url("education", self.job.id)).status_code, 404
        )
        self.assertEqual(
            self.client.get(restore_url("work", self.job.id)).status_code, 405
        )
        self.client.force_login(User.objects.create_user("bob@example.com", "x"))
        self.assertEqual(
            self.client.post(restore_url("work", self.job.id)).status_code, 404
        )
        page = self.client.get(RECENTLY_DELETED).content.decode()
        resume_table = page[page.index('id="deleted-resume-title"') :]
        self.assertIn("No deleted resume entries.", resume_table)
        self.job.refresh_from_db()
        self.assertTrue(self.job.is_deleted)

    def test_another_users_session_cannot_undo(self):
        _ = self.client.post(delete_url("work", self.job.id))
        self.client.force_login(User.objects.create_user("bob@example.com", "x"))
        _ = self.client.post(UNDO)
        self.job.refresh_from_db()
        self.assertTrue(self.job.is_deleted)

    def test_deleted_entries_do_not_count_as_duplicates_on_import(self):
        _ = self.client.post(delete_url("certifications", self.cert.id))
        session = self.client.session
        session[SESSION_KEY] = to_session(
            ResumeExtraction(certifications=[CertificationEntry("Cloud Architect")])
        )
        session.save()
        page = self.client.get(reverse("tracker:resume_import_review")).content.decode()
        self.assertNotIn("Already on your resume", page)

    def test_delete_confirmation_no_longer_says_it_cannot_be_undone(self):
        edit = reverse("tracker:resume_entry_edit", args=["work", self.job.id])
        page = self.client.get(edit).content.decode()
        self.assertIn('data-confirm="Delete Engineer at Acme from your resume?"', page)
