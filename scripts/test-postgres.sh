#!/usr/bin/env bash
# Runs the test suite against PostgreSQL in a throwaway Docker container
# (Linux and macOS; scripts/test-postgres.ps1 is the Windows version).
#
# Starts postgres:17 on localhost (port 55432 by default, so it doesn't clash
# with a PostgreSQL you already run), waits until it accepts connections, runs
# `python manage.py test` with DJANGO_DATABASE_URL pointing at it, then removes
# the container, whether the tests pass or not. Needs Docker, and the project's
# virtual environment activated (or python on the PATH).
#
# Usage:
#   ./scripts/test-postgres.sh
#   ./scripts/test-postgres.sh --port 55433 tracker.tests.test_jobs
#
# Any arguments after the options are passed on to `manage.py test`.
set -euo pipefail

port=55432
if [[ "${1:-}" == "--port" ]]; then
    if [[ -z "${2:-}" || ! "$2" =~ ^[0-9]+$ ]]; then
        echo "--port needs a port number." >&2
        exit 2
    fi
    port="$2"
    shift 2
fi

# Run from the project root, wherever the script is called from.
cd "$(dirname "$0")/.."

if command -v python >/dev/null 2>&1; then
    python=python
elif command -v python3 >/dev/null 2>&1; then
    python=python3
else
    echo "Couldn't find python: activate the project's virtual environment." >&2
    exit 1
fi

name="app-tracker-test-pg-${port}"
password="app_tracker_test"

docker run --detach --rm --name "$name" \
    --env POSTGRES_USER=app_tracker \
    --env POSTGRES_PASSWORD="$password" \
    --env POSTGRES_DB=app_tracker \
    --publish "127.0.0.1:${port}:5432" \
    postgres:17 >/dev/null

# Remove the container however the script ends (including Ctrl+C).
trap 'docker stop "$name" >/dev/null 2>&1 || true' EXIT

echo "Waiting for PostgreSQL on port ${port}..."
ready=false
for _ in $(seq 1 60); do
    if docker exec "$name" pg_isready --username=app_tracker --dbname=app_tracker >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
if [[ "$ready" != true ]]; then
    echo "PostgreSQL didn't become ready within 60 seconds." >&2
    exit 1
fi

# ${@+"$@"}: the arguments, if any (an empty "$@" trips `set -u` in the bash
# 3.2 that macOS ships).
DJANGO_DATABASE_URL="postgres://app_tracker:${password}@127.0.0.1:${port}/app_tracker" \
    "$python" manage.py test ${@+"$@"}
