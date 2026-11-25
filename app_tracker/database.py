"""Which database the app uses: SQLite by default, or PostgreSQL.

Set DJANGO_DATABASE_URL to use PostgreSQL, for example:

    postgres://app_tracker:<password>@localhost:5432/app_tracker
    postgres://app_tracker:<password>@db.example.com:5432/app_tracker?sslmode=require

Query parameters such as sslmode are passed to the PostgreSQL driver (psycopg).
Without DJANGO_DATABASE_URL, the app uses the SQLite file at DJANGO_DB_PATH
(default: db.sqlite3 in the project folder).

DJANGO_DB_CONN_MAX_AGE sets how many seconds a PostgreSQL connection is kept
open for reuse (default 60; 0 closes it after each request).
"""

from collections.abc import Mapping
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

POSTGRES_ENGINE = "django.db.backends.postgresql"
DEFAULT_CONN_MAX_AGE = 60

type DatabaseSettings = dict[str, object]


def sqlite_settings(path: str | Path) -> DatabaseSettings:
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": path,
        # The web and API processes can share the file (on one machine, not
        # a network drive): WAL lets one read while the other writes, and
        # IMMEDIATE takes the write lock when a transaction starts, so two
        # writers wait their turn (up to `timeout` seconds) instead of failing.
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    }


def conn_max_age(environ: Mapping[str, str]) -> int:
    value = environ.get("DJANGO_DB_CONN_MAX_AGE", "").strip()
    if not value:
        return DEFAULT_CONN_MAX_AGE
    try:
        seconds = int(value)
    except ValueError:
        seconds = -1
    if seconds < 0:
        raise ImproperlyConfigured(
            f'DJANGO_DB_CONN_MAX_AGE must be a whole number of seconds, not "{value}".'
        )
    return seconds


def postgres_settings(url: str, environ: Mapping[str, str]) -> DatabaseSettings:
    try:
        parsed = dj_database_url.parse(
            url,
            conn_max_age=conn_max_age(environ),
            # A connection dropped while it was kept open (a database
            # restart, a network blip) is replaced instead of failing a request.
            conn_health_checks=True,
        )
    except ValueError as error:
        raise ImproperlyConfigured(
            "DJANGO_DATABASE_URL isn't a valid database URL."
        ) from error
    # The URL may hold a password: never repeat it in the message.
    if parsed.get("ENGINE") != POSTGRES_ENGINE:
        raise ImproperlyConfigured(
            "DJANGO_DATABASE_URL must be a PostgreSQL URL (postgres://...)."
        )
    return dict(parsed)


def database_settings(
    environ: Mapping[str, str], base_dir: Path
) -> dict[str, DatabaseSettings]:
    """settings.DATABASES for the given environment variables."""
    # Kept out of the settings module's own names: it may hold a password,
    # which Django's error reports would show for a setting called *_URL.
    url = environ.get("DJANGO_DATABASE_URL", "").strip()
    if url:
        return {"default": postgres_settings(url, environ)}
    return {
        "default": sqlite_settings(
            environ.get("DJANGO_DB_PATH", "") or base_dir / "db.sqlite3"
        )
    }
