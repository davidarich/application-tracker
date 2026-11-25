"""Shared helpers for the API tests (not collected as tests itself)."""

import json
from typing import ClassVar, cast, override

from django.http import HttpResponse
from django.test import TestCase

from accounts.api_tokens import issue_grant, refresh_tokens
from accounts.models import ApiGrant, User

type Json = dict[str, object]


class ApiTestCase(TestCase):
    """A user with an API grant and an access token from it, and `call()` to
    make requests with the access token."""

    user: ClassVar[User]
    grant: ClassVar[ApiGrant]
    token: ClassVar[str]  # an access token

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("owner@example.com", "x")
        cls.grant, refresh_token = issue_grant(cls.user, "Tests")
        cls.token = refresh_tokens(refresh_token).access_token

    def call(
        self,
        method: str,
        path: str,
        body: object = None,
        token: str | None = None,
        raw: str | None = None,
    ) -> HttpResponse:
        """A request to /api/v1/<path>, sending `body` as JSON (or `raw` as is)."""
        data = raw if raw is not None else "" if body is None else json.dumps(body)
        response = self.client.generic(
            method,
            f"/api/v1/{path.lstrip('/')}",
            data,
            content_type="application/json",
            headers={"Authorization": f"Bearer {token or self.token}"},
        )
        # The stubs give Client.generic() RequestFactory's return type (a request).
        return cast(HttpResponse, cast(object, response))

    def ok(
        self, method: str, path: str, body: object = None, status: int = 200
    ) -> Json:
        """The JSON of a request that must answer `status`."""
        response = self.call(method, path, body)
        self.assertEqual(response.status_code, status, response.content.decode())
        return cast(Json, response.json())

    def errors(
        self, method: str, path: str, body: object = None
    ) -> dict[str, list[str]]:
        """The field errors of a request that must be refused with a 422."""
        response = self.call(method, path, body)
        self.assertEqual(response.status_code, 422, response.content.decode())
        payload = cast(Json, response.json())
        self.assertEqual(payload["detail"], "Some fields aren't valid.")
        return cast(dict[str, list[str]], payload["errors"])


def items(page: Json) -> list[Json]:
    return cast(list[Json], page["items"])


def names(page: Json, key: str = "name") -> list[str]:
    return [cast(str, item[key]) for item in items(page)]
