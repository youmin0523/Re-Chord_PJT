# Phase B backend image — torch cu128 GPU stack + audio-separator.
#
# Build context is repo root so the same image carries `backend/`, `tests/`,
# and the lockfile. Same image serves the API and the Celery worker; the
# entrypoint runs Alembic migrations only when RUN_MIGRATIONS=1.
#
#   docker build -f deploy/backend.Dockerfile -t rechord-backend .
#
# Phase A users keep using `uv run uvicorn …` locally; this Dockerfile is
# only consumed by docker-compose.yml for staging / self-hosted deploy.

FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# System deps:
#   ffmpeg          → yt-dlp / audio I/O
#   libsndfile1     → soundfile
#   libmagic1       → python-magic on Linux (replaces python-magic-bin)
#   build-essential → wheels that compile (basic_pitch transitive deps)
#   curl            → /health healthcheck probe
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
        ffmpeg libsndfile1 libsndfile1-dev libmagic1 \
        build-essential git curl ca-certificates \
    && ln -sf /usr/bin/python3.11 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/local/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# --- Dep install layer (cached when only source changes) ----------------
COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra saas --extra monitoring --no-install-project

# --- Project source ----------------------------------------------------
COPY backend ./backend
COPY tests ./tests
COPY scripts ./scripts

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra saas --extra monitoring

COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:7860/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "7860"]
