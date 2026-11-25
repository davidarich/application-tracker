"""Profile photos: checked, cropped to a square, resized and re-encoded.

Every upload is re-saved as a fresh WebP image, so nothing but pixels is kept:
no camera metadata (such as GPS location) and no way to smuggle in a file
that only pretends to be an image.
"""

from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

AVATAR_SIZE = 256  # pixels, square
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000  # refuse huge images (e.g. decompression bombs)
ALLOWED_FORMATS = {"JPEG": "JPEG", "PNG": "PNG", "GIF": "GIF", "WEBP": "WebP"}


def process_avatar(upload: UploadedFile) -> ContentFile:
    """Turn an uploaded image into a square WebP profile photo.

    Raises ValidationError for anything that isn't a JPEG, PNG, GIF or WebP
    image of at most MAX_UPLOAD_BYTES.
    """
    allowed = ", ".join(ALLOWED_FORMATS.values())
    if (upload.size or 0) > MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"Choose an image of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB or less."
        )
    try:
        with Image.open(upload) as image:
            if image.format not in ALLOWED_FORMATS:
                raise ValidationError(f"Choose a {allowed} image.")
            if image.width * image.height > MAX_PIXELS:
                raise ValidationError("That image is too large; choose a smaller one.")
            _ = image.load()
            upright = ImageOps.exif_transpose(image)  # respect the camera's rotation
            square = ImageOps.fit(
                upright.convert("RGBA"),
                (AVATAR_SIZE, AVATAR_SIZE),
                method=Image.Resampling.LANCZOS,
            )
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise ValidationError(f"That file isn't a {allowed} image.") from None

    buffer = BytesIO()
    square.save(buffer, format="WEBP", quality=85)
    return ContentFile(buffer.getvalue(), name="avatar.webp")
