FROM python:3.13-slim

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

# Compile the Tailwind stylesheet (downloads the Tailwind CLI for this platform),
# then collect all static files for WhiteNoise to serve
RUN python manage.py tailwind build \n    && python manage.py collectstatic --noinput

# Run as an unprivileged user; /app/data holds the SQLite database and uploads
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data/uploads \
    && chown -R app:app /app/data
USER app

VOLUME ["/app/data"]
EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn app_tracker.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
