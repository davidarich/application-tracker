"""DJANGO_ROLE=api: a process that serves only the API (for its own container).

Settings are read once per process, so these run Django in a subprocess.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

# Requests the API-only process answers, with the status each should get.
PROBE = """
import django
django.setup()
from django.conf import settings
from django.test import Client
client = Client()
print("apps", ",".join(settings.INSTALLED_APPS))
for path in ("/", "/login/", "/admin/", "/profile/", "/api/v1/companies", "/api/v1/docs"):
    print(path, client.get(path).status_code)
"""


def run_django(role: str, *args: str) -> subprocess.CompletedProcess[str]:
    base = Path(__file__).resolve().parents[2]  # the project root
    with tempfile.TemporaryDirectory() as folder:
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "app_tracker.settings",
            "DJANGO_ROLE": role,
            "DJANGO_DEBUG": "0",
            "DJANGO_ALLOWED_HOSTS": "testserver",
            "DJANGO_DB_PATH": str(Path(folder) / "db.sqlite3"),
        }
        return subprocess.run(
            [sys.executable, *args],
            cwd=base,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )


class ApiRoleTests(SimpleTestCase):
    def test_the_api_role_serves_only_the_api(self):
        result = run_django("api", "-c", PROBE)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = dict(line.split(" ", 1) for line in result.stdout.splitlines())
        apps = lines.pop("apps").split(",")
        for web_only in (
            "django.contrib.admin",
            "django.contrib.sessions",
            "django_tailwind_cli",
        ):
            self.assertNotIn(web_only, apps)
        self.assertEqual(
            lines,
            {
                "/": "404",
                "/login/": "404",
                "/admin/": "404",
                "/profile/": "404",
                "/api/v1/companies": "401",
                "/api/v1/docs": "200",
            },
        )

    def test_the_api_role_passes_the_system_checks(self):
        result = run_django("api", "manage.py", "check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unknown_role_is_refused(self):
        result = run_django("worker", "manage.py", "check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DJANGO_ROLE must be "web" or "api"', result.stderr)
