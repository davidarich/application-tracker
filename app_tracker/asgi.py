"""
ASGI config for app_tracker project.

It exposes the ASGI callable as a module-level variable named ``application``.
"""

import os

from django.core.asgi import get_asgi_application

_ = os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app_tracker.settings")

application = get_asgi_application()
