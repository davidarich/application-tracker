"""
URL configuration for app_tracker project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/stable/topics/http/urls/
"""

from typing import cast

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from tracker.views import download_file

urlpatterns = [
    path("admin/", admin.site.urls),
    # Uploaded files are private: they're served only through this view, which
    # checks the file belongs to the logged-in user, never as public media.
    path(
        f"{cast(str, settings.MEDIA_URL).lstrip('/')}<path:name>",
        download_file,
        name="download_file",
    ),
    path("", include("accounts.urls")),
    path("", include("tracker.urls")),
]
