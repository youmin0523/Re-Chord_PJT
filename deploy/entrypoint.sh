#!/usr/bin/env bash
# Phase B container entrypoint.
#
# Runs Alembic migrations once at startup (idempotent) when RUN_MIGRATIONS=1
# and a DATABASE_URL is configured, then execs the requested CMD. The Celery
# worker overrides RUN_MIGRATIONS=0 in docker-compose.yml so it does not race
# the API on cold start.

set -euo pipefail

if [[ "${RUN_MIGRATIONS:-1}" == "1" && -n "${DATABASE_URL:-}" ]]; then
    echo "[entrypoint] alembic upgrade head"
    alembic -c backend/app/db/alembic.ini upgrade head
fi

exec "$@"
