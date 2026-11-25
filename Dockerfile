# Three images from one build: `web` (the site, which also serves the API),
# `api` (only the JSON API, for running it in a container of its own) and `mcp`
# (the MCP server for AI agents). A plain `docker build .` builds `web`, the
# last stage. See compose.yaml for all three.

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_DEBUG=0 \
    DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
    DJANGO_DB_PATH=/app/data/db.sqlite3 \
    DJANGO_MEDIA_ROOT=/app/data/uploads

WORKDIR /app

# Install dependencies first so this layer is cached between code changes
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user; /app/data holds the SQLite database and uploads
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data/uploads \
    && chown -R app:app /app/data

VOLUME ["/app/data"]


# --- API only ------------------------------------------------------------------
FROM base AS api

ENV DJANGO_ROLE=api

# Only the API docs' scripts and styles: no site pages, so no Tailwind build
RUN python manage.py collectstatic --noinput

USER app
EXPOSE 8001

# The web container owns the database schema: this refuses to start (and
# restarts until it's ready) while there are migrations it hasn't applied.
CMD ["sh", "-c", "python manage.py migrate --check && exec gunicorn app_tracker.wsgi:application --bind 0.0.0.0:8001 --workers 2"]


# --- MCP server ------------------------------------------------------------------
FROM base AS mcp

ENV DJANGO_ROLE=mcp

USER app
EXPOSE 8002

# Like `api`, it waits for the web container to apply migrations. Stateless,
# so any worker can answer any request.
CMD ["sh", "-c", "python manage.py migrate --check && exec uvicorn mcp_server.asgi:app --host 0.0.0.0 --port 8002 --workers 2"]


# --- Web (the default) ---------------------------------------------------------
FROM base AS web

ENV DJANGO_ROLE=web

# Compile the Tailwind stylesheet (downloads the Tailwind CLI for this platform),
# then collect all static files for WhiteNoise to serve
RUN python manage.py tailwind build \
    && python manage.py collectstatic --noinput

USER app
EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn app_tracker.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
