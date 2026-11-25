"""Custom model fields."""

import re
from typing import cast, final, override

from django.core.validators import RegexValidator
from django.db import models

# "+<country code> (<3 digits>) <3 digits>-<4 digits>", e.g. "+1 (555) 123-4567".
PHONE_NUMBER_FORMAT = re.compile(r"^\+[1-9]\d{0,2} \(\d{3}\) \d{3}-\d{4}$")
PHONE_NUMBER_EXAMPLE = "+1 (555) 123-4567"

validate_phone_number = RegexValidator(
    PHONE_NUMBER_FORMAT,
    message=f"Enter a phone number with its country code, like {PHONE_NUMBER_EXAMPLE}.",
    code="invalid_phone_number",
)


def format_phone_number(value: str) -> str:
    """Rewrite a phone number in the canonical "+1 (555) 123-4567" format.

    Punctuation and spacing are ignored: "15551234567", "+1 555.123.4567" and
    "+44 (20) 7946-0958" are all accepted. The last 10 digits are the number
    and the 1 to 3 digits before them the country code. Anything else (no
    country code, too few or too many digits) is returned unchanged, for the
    validator to reject.
    """
    digits = re.sub(r"\D", "", value)
    country_code, number = digits[:-10], digits[-10:]
    if not 1 <= len(country_code) <= 3 or country_code.startswith("0"):
        return value
    return f"+{country_code} ({number[:3]}) {number[3:6]}-{number[6:]}"


@final
class PhoneNumberField(models.CharField[str]):
    """A phone number stored as "+1 (555) 123-4567"; use max_length=20.

    Input is normalized during validation (full_clean(), so the admin and model
    forms), then checked against the format.
    """

    default_validators = (validate_phone_number,)

    @override
    def to_python(self, value: object) -> object:
        cleaned = cast(object, super().to_python(value))
        return (
            format_phone_number(cleaned)
            if isinstance(cleaned, str) and cleaned
            else cleaned
        )
