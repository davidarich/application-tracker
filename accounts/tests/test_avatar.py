"""Profile photos: uploading, processing, serving and removing."""

import tempfile
from io import BytesIO
from pathlib import Path
from typing import ClassVar, override

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from ..avatars import AVATAR_SIZE, MAX_UPLOAD_BYTES
from ..models import User


def image_upload(
    size: tuple[int, int] = (600, 300),
    image_format: str = "PNG",
    name: str = "me.png",
    gps: bool = False,
) -> SimpleUploadedFile:
    """An in-memory image file, optionally with GPS metadata in its EXIF."""
    buffer = BytesIO()
    image = Image.new("RGB", size, (200, 80, 40))
    if gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0)}  # GPSInfo
        image.save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue())


class AvatarTests(TestCase):
    media: ClassVar[tempfile.TemporaryDirectory[str]]
    user: ClassVar[User]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        # Uploads go to a temporary folder, not the real uploads/.
        cls.media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.media.cleanup)
        _ = cls.enterClassContext(override_settings(MEDIA_ROOT=cls.media.name))
        super().setUpClass()

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("ada@example.com", "x", first_name="Ada")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def upload(self, file: SimpleUploadedFile) -> str:
        response = self.client.post(
            reverse("accounts:avatar_upload"), {"photo": file}, follow=True
        )
        self.user.refresh_from_db()
        return response.content.decode()

    def stored_image(self) -> Image.Image:
        with Image.open(self.user.avatar.path) as image:
            _ = image.load()
            return image.copy()

    def test_upload_is_cropped_to_a_square_webp_under_the_users_folder(self):
        page = self.upload(image_upload((600, 300)))
        self.assertIn("Your photo has been updated.", page)
        self.assertRegex(
            self.user.avatar.name, rf"^avatars/{self.user.id}/[0-9a-f]{{32}}\.webp$"
        )
        with Image.open(self.user.avatar.path) as stored:
            self.assertEqual(stored.format, "WEBP")
        self.assertEqual(self.stored_image().size, (AVATAR_SIZE, AVATAR_SIZE))

    def test_gif_and_webp_are_accepted(self):
        for image_format, name in (("GIF", "me.gif"), ("WEBP", "me.webp")):
            with self.subTest(image_format):
                _ = self.upload(image_upload(image_format=image_format, name=name))
                self.assertEqual(self.stored_image().size, (AVATAR_SIZE, AVATAR_SIZE))

    def test_camera_metadata_is_stripped(self):
        _ = self.upload(image_upload(name="me.jpg", gps=True))
        self.assertNotIn(0x8825, self.stored_image().getexif())

    def test_rejects_files_that_arent_images(self):
        page = self.upload(SimpleUploadedFile("me.png", b"definitely not a picture"))
        self.assertIn("That file isn&#x27;t a JPEG, PNG, GIF, WebP image.", page)
        self.assertFalse(self.user.avatar)

    def test_rejects_svg(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        page = self.upload(SimpleUploadedFile("me.svg", svg))
        self.assertIn("isn&#x27;t a JPEG, PNG, GIF, WebP image", page)
        self.assertFalse(self.user.avatar)

    def test_rejects_files_over_the_size_limit(self):
        page = self.upload(SimpleUploadedFile("big.png", b"0" * (MAX_UPLOAD_BYTES + 1)))
        self.assertIn("Choose an image of 5 MB or less.", page)
        self.assertFalse(self.user.avatar)

    def test_upload_requires_a_file(self):
        page = self.client.post(
            reverse("accounts:avatar_upload"), follow=True
        ).content.decode()
        self.assertIn("Choose a photo to upload.", page)

    def test_replacing_a_photo_deletes_the_old_file(self):
        _ = self.upload(image_upload())
        old_path = Path(self.user.avatar.path)
        _ = self.upload(image_upload((300, 600)))
        self.assertFalse(old_path.exists())
        self.assertTrue(Path(self.user.avatar.path).exists())

    def test_remove_deletes_the_file_and_clears_the_photo(self):
        _ = self.upload(image_upload())
        path = Path(self.user.avatar.path)
        response = self.client.post(reverse("accounts:avatar_remove"), follow=True)
        self.assertContains(response, "Your photo has been removed.")
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)
        self.assertFalse(path.exists())

    def test_photo_is_served_only_to_its_owner(self):
        _ = self.upload(image_upload())
        response = self.client.get(reverse("accounts:avatar"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertIn("private", response["Cache-Control"])
        # Reading the file to the end lets the test client close the response
        # (and the file). Closing it here instead would close the database
        # connection too, on databases that really close it (PostgreSQL).
        self.assertTrue(response.getvalue().startswith(b"RIFF"))  # a WebP file
        # Another user only ever gets their own (here: none).
        self.client.force_login(User.objects.create_user("bob@example.com", "x"))
        self.assertEqual(self.client.get(reverse("accounts:avatar")).status_code, 404)
        self.client.logout()
        url = reverse("accounts:avatar")
        self.assertRedirects(
            self.client.get(url), f"{reverse('tracker:login')}?next={url}"
        )

    def test_header_and_profile_show_the_photo_or_the_initial(self):
        page = self.client.get(reverse("accounts:profile")).content.decode()
        self.assertNotIn(reverse("accounts:avatar") + "?v=", page)
        self.assertNotIn(">Remove</button>", page)
        _ = self.upload(image_upload())
        page = self.client.get(reverse("accounts:profile")).content.decode()
        self.assertEqual(
            page.count(reverse("accounts:avatar") + "?v="), 2
        )  # header + profile
        self.assertIn(">Remove</button>", page)

    def test_upload_and_remove_require_post(self):
        self.assertEqual(
            self.client.get(reverse("accounts:avatar_upload")).status_code, 405
        )
        self.assertEqual(
            self.client.get(reverse("accounts:avatar_remove")).status_code, 405
        )


class AvatarCleanupTests(TransactionTestCase):
    """Deleting a user deletes their photo file, once the deletion commits.

    A TransactionTestCase, so deletions really commit (or roll back).
    """

    media: ClassVar[tempfile.TemporaryDirectory[str]]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.media.cleanup)
        _ = cls.enterClassContext(override_settings(MEDIA_ROOT=cls.media.name))
        super().setUpClass()

    def user_with_photo(self, email: str) -> tuple[User, Path]:
        user = User.objects.create_user(email, "x")
        self.client.force_login(user)
        _ = self.client.post(
            reverse("accounts:avatar_upload"), {"photo": image_upload()}
        )
        user.refresh_from_db()
        path = Path(user.avatar.path)
        self.assertTrue(path.exists())
        return user, path

    def test_deleting_a_user_deletes_their_photo(self):
        user, path = self.user_with_photo("ada@example.com")
        _ = user.delete()
        self.assertFalse(path.exists())

    def test_bulk_deleting_users_deletes_their_photos(self):
        _, ada_path = self.user_with_photo("ada@example.com")
        _, bob_path = self.user_with_photo("bob@example.com")
        _ = User.objects.filter(
            email__in=["ada@example.com", "bob@example.com"]
        ).delete()
        self.assertFalse(ada_path.exists())
        self.assertFalse(bob_path.exists())

    def test_a_rolled_back_deletion_keeps_the_photo(self):
        user, path = self.user_with_photo("ada@example.com")
        with self.assertRaises(RuntimeError), transaction.atomic():
            _ = user.delete()
            raise RuntimeError("roll back")
        self.assertTrue(User.objects.filter(email="ada@example.com").exists())
        self.assertTrue(path.exists())

    def test_deleting_a_user_without_a_photo_is_fine(self):
        user = User.objects.create_user("new@example.com", "x")
        _ = user.delete()
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_other_users_photos_are_kept(self):
        user, _ = self.user_with_photo("ada@example.com")
        _, other_path = self.user_with_photo("bob@example.com")
        _ = user.delete()
        self.assertTrue(other_path.exists())
