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

# Cloud Run / Fly / Railway / Heroku / Render all inject ``$PORT`` for the
# bind address. Local docker-compose leaves it unset so we fall back to
# 7860. We rewrite the uvicorn command in place so the same image runs
# in both worlds without per-platform configuration.
if [[ "$1" == "uvicorn" && -n "${PORT:-}" ]]; then
    echo "[entrypoint] PORT=$PORT detected → rewriting --port"
    args=()
    skip_next=0
    for a in "$@"; do
        if (( skip_next )); then skip_next=0; continue; fi
        if [[ "$a" == "--port" ]]; then skip_next=1; continue; fi
        args+=("$a")
    done
    exec "${args[@]}" --port "$PORT"
fi

exec "$@"
