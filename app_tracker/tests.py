"""Choosing the database: SQLite by default, PostgreSQL by DJANGO_DATABASE_URL."""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from .database import database_settings

BASE = Path("/srv/app")


class DatabaseSettingsTests(SimpleTestCase):
    def test_sqlite_by_default(self):
        default = database_settings({}, BASE)["default"]
        self.assertEqual(default["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(default["NAME"], BASE / "db.sqlite3")
        self.assertEqual(
            database_settings({"DJANGO_DB_PATH": "/data/app.db"}, BASE)["default"][
                "NAME"
            ],
            "/data/app.db",
        )
        # An empty or blank URL (e.g. passed through by Compose) means SQLite too.
        for url in ("", "   "):
            settings = database_settings({"DJANGO_DATABASE_URL": url}, BASE)
            self.assertEqual(
                settings["default"]["ENGINE"], "django.db.backends.sqlite3"
            )

    def test_postgres_from_the_url(self):
        url = "postgres://tracker:s3cret@db.example.com:5433/tracker?sslmode=require"
        default = database_settings({"DJANGO_DATABASE_URL": url}, BASE)["default"]
        self.assertEqual(
            {
                k: default[k]
                for k in ("ENGINE", "NAME", "USER", "PASSWORD", "HOST", "PORT")
            },
            {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "tracker",
                "USER": "tracker",
                "PASSWORD": "s3cret",
                "HOST": "db.example.com",
                "PORT": 5433,
            },
        )
        self.assertEqual(default["OPTIONS"], {"sslmode": "require"})
        self.assertEqual(
            (default["CONN_MAX_AGE"], default["CONN_HEALTH_CHECKS"]), (60, True)
        )
        # postgresql:// is the same.
        other = database_settings({"DJANGO_DATABASE_URL": "postgresql://a:b@h/n"}, BASE)
        self.assertEqual(other["default"]["ENGINE"], "django.db.backends.postgresql")

    def test_connection_reuse_can_be_set(self):
        environ = {
            "DJANGO_DATABASE_URL": "postgres://a:b@h/n",
            "DJANGO_DB_CONN_MAX_AGE": "0",
        }
        self.assertEqual(database_settings(environ, BASE)["default"]["CONN_MAX_AGE"], 0)
        for bad in ("soon", "-5", "1.5"):
            with self.assertRaisesMessage(
                ImproperlyConfigured, "DJANGO_DB_CONN_MAX_AGE"
            ):
                _ = database_settings({**environ, "DJANGO_DB_CONN_MAX_AGE": bad}, BASE)

    def test_only_postgres_urls_are_accepted(self):
        for url in (
            "mysql://a:secret@h/n",
            "sqlite:///tmp/db.sqlite3",
            "oracle://a:secret@h/n",
            "nonsense://a:secret@h/n",
        ):
            with self.assertRaises(ImproperlyConfigured) as caught:
                _ = database_settings({"DJANGO_DATABASE_URL": url}, BASE)
            self.assertNotIn("secret", str(caught.exception))  # never echo the password
