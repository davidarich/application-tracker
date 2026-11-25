"""The phone number field."""

from django.test import TestCase

from ..fields import format_phone_number


class PhoneNumberTests(TestCase):
    def test_formats_numbers_with_a_country_code(self):
        cases = {
            "15551234567": "+1 (555) 123-4567",
            "+1 555.123.4567": "+1 (555) 123-4567",
            "+1 (555) 123-4567": "+1 (555) 123-4567",
            "+44 20 7946 0958": "+44 (207) 946-0958",
            "+353 555 123 4567": "+353 (555) 123-4567",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(format_phone_number(raw), expected)

    def test_leaves_unparseable_numbers_for_the_validator(self):
        # No country code, too short, a 0 country code, a 4-digit country code.
        for raw in ["5551234567", "123", "+0 555 123 4567", "+1234 555 123 4567"]:
            with self.subTest(raw=raw):
                self.assertEqual(format_phone_number(raw), raw)
