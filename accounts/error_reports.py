"""Keeping API tokens out of error reports.

When a request fails with a server error, Django can send a report with the
request's POST data and each traceback frame's local variables (by email to
ADMINS, or to an error tracker). It already hides the Authorization header, but
not the token endpoint's `refresh_token` parameter or variables that hold a
token. This filter (settings.DEFAULT_EXCEPTION_REPORTER_FILTER) hides those too.
Like Django's own filter, it's active when DEBUG is off.
"""

import re
from typing import cast, override

from django.http import HttpRequest, QueryDict
from django.views.debug import SafeExceptionReporterFilter

# POST parameters that are always secret (RFC 6749 section 6 names the first).
TOKEN_PARAMETERS = frozenset({"refresh_token", "access_token"})
# Anything that looks like one of our tokens (accounts/api_tokens.py).
TOKEN_RE = re.compile(r"(?:at|rt)_[A-Za-z0-9_-]{20,}")


class TokenSafeExceptionReporterFilter(SafeExceptionReporterFilter):
    def hide_tokens(self, parameters: QueryDict) -> QueryDict:
        cleansed = parameters.copy()
        for key, value in parameters.items():
            if key in TOKEN_PARAMETERS or TOKEN_RE.search(str(value)):
                cleansed[key] = self.cleansed_substitute
        return cleansed

    @override
    def get_post_parameters(self, request: HttpRequest | None) -> dict[str, object]:
        parameters = super().get_post_parameters(request)
        if request is None or not self.is_active(request):
            return parameters
        if isinstance(parameters, QueryDict):
            # Django returns request.POST here, despite the stubs' dict type.
            return cast(dict[str, object], cast(object, self.hide_tokens(parameters)))
        return parameters

    @override
    def get_cleansed_multivaluedict(
        self, request: HttpRequest, multivaluedict: QueryDict
    ) -> QueryDict:
        cleansed = super().get_cleansed_multivaluedict(request, multivaluedict)
        return self.hide_tokens(cleansed) if self.is_active(request) else cleansed

    @override
    def cleanse_special_types(
        self, request: HttpRequest | None, value: object
    ) -> object:
        """Frame variables: a string holding a token is hidden."""
        if (
            self.is_active(request)
            and isinstance(value, str)
            and TOKEN_RE.search(value)
        ):
            return self.cleansed_substitute
        return cast(object, super().cleanse_special_types(request, value))
