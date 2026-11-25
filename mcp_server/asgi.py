"""The MCP server's ASGI app, for uvicorn:

DJANGO_ROLE=mcp uvicorn mcp_server.asgi:app --port 8002
"""

import os

import django

_ = os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app_tracker.settings")
_ = os.environ.setdefault("DJANGO_ROLE", "mcp")
django.setup()

from .server import build_app  # (after Django is set up)

app = build_app()
