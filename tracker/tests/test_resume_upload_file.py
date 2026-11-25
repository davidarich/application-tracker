"""Uploaded resume PDFs are kept (uploads/resumes/) and can be downloaded."""

from pathlib import Path
from typing import ClassVar, override

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import User

from ..ownership import resume_for
from .helpers import owner, temporary_media
from .pdf_builder import Text, build_pdf

UPLOAD = reverse("tracker:resume_import")
DOWNLOAD = reverse("tracker:resume_file")


def resume_pdf(text: str = "EXPERIENCE") -> bytes:
    return build_pdf(
        [
            [
                Text(40, 40, text, 12, True),
                Text(40, 70, "Engineer at Acme Inc.\t2020 - 2021"),
            ]
        ]
    )


class ResumeFileTests(TestCase):
    media: ClassVar[Path]
    user: ClassVar[User]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.media = temporary_media(cls)
        super().setUpClass()

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def upload(self, data: bytes, name: str = "Jane Doe - Resume.pdf") -> None:
        _ = self.client.post(UPLOAD, {"file": SimpleUploadedFile(name, data)})

    def test_upload_is_saved_under_uploads_resumes(self):
        data = resume_pdf()
        self.upload(data)
        resume = resume_for(self.user)
        self.assertTrue(resume.file.name.startswith(f"resumes/{self.user.id}/"))
        self.assertTrue(resume.file.name.endswith(".pdf"))
        self.assertNotIn(
            "Jane", resume.file.name
        )  # the original name stays out of the path
        self.assertEqual(Path(resume.file.path).read_bytes(), data)
        self.assertTrue(Path(resume.file.path).is_relative_to(self.media / "resumes"))
        self.assertEqual(resume.file_name, "Jane Doe - Resume.pdf")
        self.assertIsNotNone(resume.file_uploaded_at)

    def test_files_that_cannot_be_read_are_not_saved(self):
        before = set(self.media.rglob("*.pdf"))
        self.upload(build_pdf([[]]))  # no text
        self.upload(b"not a pdf", "notes.txt")
        self.assertFalse(resume_for(self.user).file)
        self.assertEqual(set(self.media.rglob("*.pdf")), before)

    def test_a_new_upload_replaces_and_deletes_the_old_file(self):
        self.upload(resume_pdf("EXPERIENCE"), "old.pdf")
        old_path = Path(resume_for(self.user).file.path)
        self.upload(resume_pdf("WORK HISTORY"), "new.pdf")
        resume = resume_for(self.user)
        self.assertEqual(resume.file_name, "new.pdf")
        self.assertFalse(old_path.exists())
        self.assertTrue(Path(resume.file.path).exists())

    def test_resume_page_links_to_the_uploaded_file(self):
        self.assertNotIn(
            DOWNLOAD, self.client.get(reverse("tracker:resume")).content.decode()
        )
        self.upload(resume_pdf())
        page = self.client.get(reverse("tracker:resume")).content.decode()
        self.assertIn(f'href="{DOWNLOAD}"', page)
        self.assertIn("Jane Doe - Resume.pdf", page)

    def test_download_serves_your_own_file(self):
        data = resume_pdf()
        self.upload(data)
        response = self.client.get(DOWNLOAD)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(
            'filename="Jane Doe - Resume.pdf"', response["Content-Disposition"]
        )
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(b"".join(response.streaming_content), data)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownArgumentType, reportUnknownMemberType]

    def test_download_without_a_file_or_login(self):
        self.assertEqual(self.client.get(DOWNLOAD).status_code, 404)
        self.upload(resume_pdf())
        self.client.force_login(User.objects.create_user("bob@example.com", "x"))
        self.assertEqual(self.client.get(DOWNLOAD).status_code, 404)  # Bob has none
        self.client.logout()
        self.assertRedirects(
            self.client.get(DOWNLOAD), f"{reverse('tracker:login')}?next={DOWNLOAD}"
        )

    def test_upload_page_says_the_file_is_kept(self):
        self.assertContains(
            self.client.get(UPLOAD), "Your file is saved with your resume"
        )


class ResumeFileDeletionTests(TransactionTestCase):
    """Deleting a user deletes their uploaded resume, once the deletion commits.

    A TransactionTestCase, so deletions really commit (or roll back).
    """

    @classmethod
    @override
    def setUpClass(cls) -> None:
        _ = temporary_media(cls)
        super().setUpClass()

    def user_with_resume(self) -> tuple[User, Path]:
        user = User.objects.create_user("ada@example.com", "x")
        self.client.force_login(user)
        _ = self.client.post(
            UPLOAD, {"file": SimpleUploadedFile("cv.pdf", resume_pdf())}
        )
        path = Path(resume_for(user).file.path)
        self.assertTrue(path.exists())
        return user, path

    def test_deleting_a_user_deletes_their_resume_file(self):
        user, path = self.user_with_resume()
        _ = user.delete()
        self.assertFalse(path.exists())

    def test_a_rolled_back_deletion_keeps_the_file(self):
        user, path = self.user_with_resume()
        with self.assertRaises(RuntimeError), transaction.atomic():
            _ = user.delete()
            raise RuntimeError("roll back")
        self.assertTrue(path.exists())
