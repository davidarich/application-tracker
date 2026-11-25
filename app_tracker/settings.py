"""
Django settings for app_tracker project.

For more information on this file, see
https://docs.djangoproject.com/en/stable/topics/settings/
"""

import os
from pathlib import Path

import django_stubs_ext
from django.core.exceptions import ImproperlyConfigured

# Let Django classes such as ModelAdmin take type arguments at runtime
# (e.g. ModelAdmin[Company]), as the type stubs expect.
django_stubs_ext.monkeypatch()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/stable/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-hc(o&m72ka32qxcd3)wu%xb1amgj1982gp=vfph2%ep8mlk3k%",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]


# What this process serves:
#   web  the site, with the JSON API at /api/v1/ too (the default)
#   api  only the JSON API (api/urls.py), e.g. in a container of its own; no
#        pages, admin, sessions or CSRF, since API requests use bearer tokens
ROLE = os.environ.get("DJANGO_ROLE", "web")
if ROLE not in {"web", "api"}:
    raise ImproperlyConfigured(f'DJANGO_ROLE must be "web" or "api", not "{ROLE}".')


# Application definition

API_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    # Serves the API docs' own scripts and styles (no CDN).
    "django.contrib.staticfiles",
    "ninja",
    "accounts",
    "tracker",
    "api",
]
WEB_APPS = [
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django_tailwind_cli",
    *API_APPS,
]
INSTALLED_APPS = WEB_APPS if ROLE == "web" else API_APPS

API_MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]
WEB_MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
MIDDLEWARE = WEB_MIDDLEWARE if ROLE == "web" else API_MIDDLEWARE

ROOT_URLCONF = "app_tracker.urls" if ROLE == "web" else "api.urls"

TEMPLATES: list[dict[str, object]] = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "app_tracker.wsgi.application"


# Database
# https://docs.djangoproject.com/en/stable/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
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
}


# Password validation
# https://docs.djangoproject.com/en/stable/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Authentication
# https://docs.djangoproject.com/en/stable/topics/auth/default/

# Users log in with their email address (accounts.models.User).
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "tracker:login"
LOGIN_REDIRECT_URL = "tracker:dashboard"
LOGOUT_REDIRECT_URL = "tracker:login"


# Error reports (emails to ADMINS, error trackers) leave out API tokens, as
# well as the passwords and keys Django already hides.
DEFAULT_EXCEPTION_REPORTER_FILTER = (
    "accounts.error_reports.TokenSafeExceptionReporterFilter"
)


# Internationalization
# https://docs.djangoproject.com/en/stable/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/stable/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# The site's own assets; the API serves only the docs' files from apps.
STATICFILES_DIRS = [BASE_DIR / "assets"] if ROLE == "web" else []

# Tailwind CSS (django-tailwind-cli)
# https://django-tailwind-cli.rtfd.io/
# `manage.py tailwind build` compiles tailwind/app.css (the theme and source)
# into assets/css/tailwind.css, which is generated and not committed.
TAILWIND_CLI_SRC_CSS = "tailwind/app.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"
TAILWIND_CLI_VERSION = "4.3.5"

# User-uploaded files
# https://docs.djangoproject.com/en/stable/topics/files/

MEDIA_URL = "uploads/"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "uploads"))

# Default primary key field type
# https://docs.djangoproject.com/en/stable/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
