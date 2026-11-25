"""
WSGI config for app_tracker project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os

from django.core.wsgi import get_wsgi_application

_ = os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app_tracker.settings")

application = get_wsgi_application()
