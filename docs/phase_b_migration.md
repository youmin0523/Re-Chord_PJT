# Phase A → Phase B Migration Playbook

Phase A is the single-machine local stack you've been running with `uv run
uvicorn …` and `npm run dev`. Phase B is the SaaS-shaped deployment:
Postgres for persistence, Redis-backed Celery for queueing, object storage
for artifacts, and an auth provider in front of `/jobs`.

The backend is designed so **Phase A behaviour stays identical** until you
opt in to each Phase B component via env vars. You don't have to migrate
everything at once — turn things on stage by stage.

> See also: [`deployment.md`](deployment.md) for the production checklist
> and `docker-compose.yml` for the reference compose stack that wires all
> of this up together.

---

## At a glance

| Component | Env switch | Phase A fallback |
|-----------|------------|------------------|
| Persistence | `DATABASE_URL=postgresql+asyncpg://…` | In-process job registry |
| Queue | `CELERY_BROKER_URL=redis://…` | Asyncio task pool |
| Storage | `STORAGE_BACKEND=s3` / `r2` + `AWS_*` | Local `data/` mount |
| Auth | `AUTH_PROVIDER=clerk` + `CLERK_JWKS_URL` | Guest mode |
| Logging | `RECHORD_LOG_FORMAT=json` + `SENTRY_DSN` | Plain text to stdout |

---

## 0. Pre-flight

```bash
# Add the SaaS deps (alembic, asyncpg, sqlalchemy[asyncio]).
uv pip install -e ".[saas,monitoring]"

# Verify the migration tree is intact.
uv run alembic -c backend/app/db/alembic.ini history
```

Run a clean accuracy gate against Phase A first; if any baseline regresses
in the move you want a known-good reference:

```bash
uv run python -m pytest tests/test_accuracy_thresholds.py
```

---

## 1. Postgres (persistence)

Phase A keeps jobs in `core/jobs.py::registry` (in-process dict). A
restart drops them. Phase B writes them to Postgres via
`backend/app/db/repository.py`.

### Bring up the database

The compose file ships a healthchecked `postgres:16-alpine`:

```bash
docker compose up -d postgres
docker compose exec postgres pg_isready -U rechord -d rechord
```

Or point at a managed Postgres (Supabase, Neon, RDS, …) by setting
`DATABASE_URL` directly.

### Run migrations

The backend container's entrypoint (`deploy/entrypoint.sh`) runs
`alembic upgrade head` automatically on boot when `RUN_MIGRATIONS=1`.
For local cutover, run it manually first so you can read the output:

```bash
DATABASE_URL=postgresql+asyncpg://rechord:rechord_dev@localhost:5432/rechord \
  uv run alembic -c backend/app/db/alembic.ini upgrade head
```

You should see `798e2cd5eda2_init_schema` and `a1b2c3d4e5f6_add_chat_tables`
applied.

### Sanity check

```bash
DATABASE_URL=… uv run uvicorn backend.app.main:app --port 7860
curl -s http://localhost:7860/health | jq .status
```

Submit a Quick MR job and confirm a row appears in the `jobs` table.

### Rollback

Migrations are reversible: `alembic downgrade -1`. Drop the database
and re-create if you need to wipe state — the schema is small enough
that a fresh `upgrade head` is fast.

---

## 2. Redis + Celery (queue)

Phase A's `core/queue.py` is an asyncio task pool: one process owns all
jobs, and a crash loses anything in flight. Phase B routes the heavy
work through Celery so a separate worker container can be scaled
horizontally and tolerate restarts.

### Bring up Redis + a worker

```bash
docker compose up -d redis worker
```

The worker container reuses the same image as the API but overrides the
CMD to `celery -A backend.app.workers.celery_app worker -l info -c 2`.
It waits for `backend` to be healthy before starting (see compose
`depends_on:` block) so migrations have already applied.

### Verify the wiring

```bash
# From any container with the deps:
celery -A backend.app.workers.celery_app inspect ping
celery -A backend.app.workers.celery_app inspect registered | grep run_job
```

You should see `rechord.run_job` listed.

### Submit a job

With both `DATABASE_URL` and `CELERY_BROKER_URL` set, `POST /jobs` will
return immediately and the worker picks it up. The progress WebSocket
keeps working — the orchestrator publishes the same events whether it
runs in-process or in a Celery task.

### Tuning

| Knob | Default | When to change |
|------|---------|----------------|
| `-c 2` (concurrency) | 2 | One per GPU you want utilised in parallel |
| `task_acks_late=True` | on | Keep on; redelivers in-flight jobs after a crash |
| `worker_prefetch_multiplier=1` | 1 | Don't raise — heavy jobs starve cheap ones at >1 |
| `result_expires` | 7d | Lower if you don't poll results from the queue |

### Rollback

Unset `CELERY_BROKER_URL` and restart the API. The asyncio pool comes
back; no schema/state change needed.

---

## 3. Object storage (S3 / R2)

Phase A writes every artifact under `data/jobs/{id}/`. That works on a
single box but doesn't survive container restarts in a managed runtime
and can't be served straight from a CDN.

### Mirror to R2/S3

Set:

```bash
STORAGE_BACKEND=r2                 # or s3
STORAGE_BUCKET=rechord-prod
STORAGE_REGION=apac
AWS_ACCESS_KEY_ID=…
AWS_SECRET_ACCESS_KEY=…
AWS_ENDPOINT_URL=https://…r2.cloudflarestorage.com   # R2 only
```

The mirror helper (`backend/app/storage/mirror.py`) writes the local
file first, then PUTs to the bucket asynchronously. Download URLs in
the API response prefer the bucket-served URL when it's reachable.

### Cutover

R2 / S3 is safe to enable on day one of Phase B even if you keep
everything else local — failures degrade gracefully back to local file
serving. We **recommend enabling storage first** (lowest risk, lets you
later swap out the compute layer without losing user artifacts).

### Migration of existing artifacts

The mirror only catches new writes. To backfill:

```bash
uv run python scripts/storage_backfill.py --src data/jobs --bucket rechord-prod
```

(Phase A users may not have this script yet — it'll appear when the
storage mirror lands. Until then, leave existing local jobs as-is;
they keep working through the legacy serving path.)

---

## 4. Auth (Clerk / Supabase)

Phase A is **guest-only by design** (memory: `auth_deferred.md`). When
Phase B opens up paid plans you flip on a provider:

```bash
AUTH_PROVIDER=clerk
CLERK_ISSUER=https://your-app.clerk.accounts.dev
CLERK_JWKS_URL=https://your-app.clerk.accounts.dev/.well-known/jwks.json
```

Verify any authenticated request:

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:7860/jobs
```

A missing/bad token returns 401; existing guest users keep working for
endpoints that allow `anonymous: true` (download by job id remains
public — they only need the opaque `job_id`).

For the Korean rollout we plan a Supabase + Kakao login flow; the same
`AUTH_PROVIDER` switch handles it once the Supabase adapter is wired.

---

## 5. Observability

Already covered in [`deployment.md` §0](deployment.md), but for Phase B
specifically you'll want:

* `RECHORD_LOG_FORMAT=json` — required for Loki/Datadog ingestion.
* `SENTRY_DSN` set — every `capture_exception` call in the orchestrator
  forwards there; without it, errors only land in stdout.
* Datadog / Grafana dashboard for `job.meta.quality_grade`, `lufs_error_db`,
  WebSocket reconnect rate (the `/jobs/:id/progress` socket now emits
  `reconnecting` / `failed` status events to the client — mirror this
  into a server-side metric if you want a top-line "Phase B WS health"
  signal).

---

## 6. Cold-start strategy (Cloud Run / serverless GPU)

Memory plan: API on Cloud Run Seoul, GPU workers on a serverless GPU
provider with keep-warm during worship-service hours (Sun 06-13 KST).
Order of operations on a cold instance:

1. Image pulls (~30s on first cold start, mostly torch + audio-separator wheels).
2. Entrypoint runs `alembic upgrade head` — fast no-op once the DB is current.
3. `uvicorn` binds; the `/health` healthcheck waits for 60s start period.
4. First job triggers separator model load (~10-25s with cu128 wheel cache).

To smooth Sunday-morning load:

* Run a **prewarm worker** in the worship window that submits a one-second
  silent clip to keep weights in GPU memory between real jobs.
* Set Celery `worker_prefetch_multiplier=1` (already default) so a single
  long job can't block a quick request behind it.

---

## Migration checklist

Tick top-to-bottom:

- [ ] [`deployment.md §0`](deployment.md) baseline (Sentry/structlog) on.
- [ ] `uv pip install -e ".[saas,monitoring]"`
- [ ] Postgres reachable; `alembic upgrade head` runs clean.
- [ ] API serves with `DATABASE_URL` set; one Quick MR job round-trips.
- [ ] Redis up; `celery inspect ping` succeeds.
- [ ] One Quick MR via Celery queue; progress WS still streams events.
- [ ] R2/S3 mirror enabled; download URL serves from bucket.
- [ ] Auth provider issuer/JWKS configured; protected endpoints 401 on
      missing token.
- [ ] Accuracy gate runs in the new env (`pytest tests/test_accuracy_thresholds.py`).
- [ ] Sentry sees a deliberately-thrown test exception with the right
      `RECHORD_ENV` tag.
