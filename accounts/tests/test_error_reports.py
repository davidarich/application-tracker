"""Server error reports never include API tokens."""

import sys
from types import TracebackType

from django.test import RequestFactory, TestCase, override_settings
from django.views.debug import ExceptionReporter

from ..api_tokens import TokenPair, issue_grant
from ..models import User

ACCESS_TOKEN = "at_" + "A1b2C3d4E5" * 4 + "xyz"


def failing(request_token: str) -> None:
    """Fails with tokens in its local variables, under innocent names too."""
    value = request_token
    pair = TokenPair(access_token=ACCESS_TOKEN, refresh_token=value, expires_in=900)
    raise ValueError(f"boom ({len(repr(pair))})")


def error_info(token: str) -> tuple[type[BaseException], BaseException, TracebackType]:
    try:
        failing(token)
    except ValueError:
        exc_type, exc_value, tb = sys.exc_info()
        assert exc_type is not None and exc_value is not None and tb is not None
        return exc_type, exc_value, tb
    raise AssertionError("failing() didn't fail")


@override_settings(DEBUG=False)
class ErrorReportTests(TestCase):
    def test_tokens_are_left_out_of_error_reports(self):
        _grant, refresh_token = issue_grant(
            User.objects.create_user("a@example.com", "x"), "S"
        )
        request = RequestFactory().post(
            "/api/v1/oauth/token",
            "grant_type=refresh_token&refresh_token="
            + refresh_token
            + "&note="
            + refresh_token,
            content_type="application/x-www-form-urlencoded",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        )
        reporter = ExceptionReporter(request, *error_info(refresh_token))
        for report in (reporter.get_traceback_text(), reporter.get_traceback_html()):
            self.assertNotIn(refresh_token, report)
            self.assertNotIn(refresh_token[3:], report)
            self.assertNotIn(ACCESS_TOKEN[3:], report)
            self.assertIn("boom", report)  # the report itself is still there
            self.assertIn("refresh_token", report)  # with the parameter's name
            self.assertIn("grant_type", report)

    def test_authorization_codes_and_verifiers_are_left_out_too(self):
        code = "ac_" + "Z9y8X7w6V5" * 4 + "abc"
        verifier = "v3r1f13r-" * 6
        request = RequestFactory().post(
            "/api/v1/oauth/token",
            "grant_type=authorization_code&code=" + code + "&code_verifier=" + verifier,
            content_type="application/x-www-form-urlencoded",
        )
        reporter = ExceptionReporter(request, *error_info(code))
        for report in (reporter.get_traceback_text(), reporter.get_traceback_html()):
            self.assertNotIn(code[3:], report)
            self.assertNotIn(verifier, report)
            self.assertIn("code_verifier", report)

    def test_token_pairs_never_show_their_tokens(self):
        pair = TokenPair(
            access_token=ACCESS_TOKEN, refresh_token="rt_secret", expires_in=900
        )
        self.assertEqual(repr(pair), "TokenPair(expires_in=900)")
