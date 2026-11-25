from typing import final

from django.apps import AppConfig


@final
class ApiConfig(AppConfig):
    """The JSON API (Django Ninja) for jobs, companies and skills, at /api/v1/."""

    name = "api"
    verbose_name = "API"
