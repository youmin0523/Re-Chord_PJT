# Re:Chord — Deployment Guide

Phase-by-phase production checklist. Designed to be followed top-to-bottom
the first time you ship to a non-dev environment.

---

## 0. Environment & monitoring baseline

Required before any user-visible deploy:

```bash
# Install monitoring stack (Sentry + structlog already in deps)
uv pip install -e ".[monitoring]"
```

Set the following env vars (or copy `.env.example` → `.env`):

```bash
RECHORD_ENV=prod                    # appears in every Sentry event
RECHORD_RELEASE=0.3.0               # tags errors with the build version
RECHORD_LOG_FORMAT=json             # required for Datadog / Loki / Cloudwatch
RECHORD_LOG_LEVEL=INFO              # WARN for noisy stages, INFO otherwise

SENTRY_DSN=https://…                # leave empty to disable Sentry
SENTRY_TRACES_SAMPLE_RATE=0.05      # 5% perf sampling; raise/lower per traffic
```

Verify wiring:

```bash
uv run python -c "from backend.app.core.observability import setup_logging; \
                  setup_logging(); \
                  import logging; logging.getLogger('rechord').info('boot ok')"
```

The line should appear as a JSON object when `RECHORD_LOG_FORMAT=json`.

---

## 1. SOTA model accuracy baseline

For commercial release you almost certainly want every optional backend
installed. Anything missing degrades a specific stage by a measurable
amount:

| Stage           | Missing dep                          | Impact                                              |
|-----------------|--------------------------------------|-----------------------------------------------------|
| chord_detect    | `crema`                              | falls back to 24 triads (no 7th/sus/slash)          |
| key_detect      | `madmom`                             | librosa Krumhansl ~70-80% vs CNN ~85-92%            |
| beat_grid       | `madmom`                             | no DBN downbeat tracking on compound meters         |
| transcribe_piano| `piano_transcription_inference`      | basic-pitch ~70% vs PTI ~83% F1                     |
| transcribe_bass | `crepe`                              | basic-pitch ~78% vs CREPE ~91% F1                   |
| transcribe_drums| `omnizart` (Python 3.10 only)        | heuristic ~72% vs SOTA ~88% F1                      |
| aux_classifier  | `laion-clap`                         | AUX patch auto-suggest disabled                     |
| lyrics          | `faster-whisper`                     | lyric transcription disabled                        |

Install everything that fits your Python version:

```bash
uv pip install -e ".[sota_models,aux_classifier,monitoring]"
uv pip install crepe --no-build-isolation
uv pip install piano_transcription_inference
# madmom requires MSVC on Windows or build-essential on Linux:
uv pip install "madmom>=0.16.1" --no-build-isolation
```

Verify which backends are live at runtime:

```bash
curl http://127.0.0.1:7860/ops/install_hints | jq
```

The `all_installed: true` flag is what commercial release should target.

---

## 2. Accuracy gate

Before deploying a new release tag, run the suite:

```bash
uv run python scripts/run_accuracy_suite.py
```

This script:
1. measures synth-signal accuracy (key/BPM/onset/chord)
2. attempts real-world URL-grounded measurement (needs backend up)
3. invokes pytest `tests/test_accuracy_thresholds.py` which **fails**
   when any metric is below the documented minimum in
   `tests/fixtures/accuracy_thresholds.json`

Threshold updates require an explicit commit to that JSON — the gate
catches accidental regressions and unintentional improvements alike.

---

## 3. Phase A → Phase B migration

Phase A runs entirely on a single machine. Phase B adds:

| Component   | Activated by env var                              |
|-------------|---------------------------------------------------|
| Postgres    | `DATABASE_URL=postgresql+asyncpg://…`             |
| S3/R2       | `STORAGE_BACKEND=s3` or `r2` + AWS_*              |
| Redis/Celery| `CELERY_BROKER_URL=redis://…`                     |
| Auth (Clerk)| `AUTH_PROVIDER=clerk` + `CLERK_JWKS_URL`          |

The backend is built so Phase A behaviour is *identical* until one of
these env vars is set. To migrate:

```bash
uv pip install -e ".[saas]"
# Bring up Postgres + Redis (see docker-compose.yml for a local profile).
docker-compose up -d postgres redis

# Run migrations.
uv run alembic -c backend/app/db/alembic.ini upgrade head

# Start workers.
RECHORD_ENV=stage uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 7860
```

---

## 4. CI/CD gates

The `.github/workflows/ci.yml` lanes:

* **backend** — ruff lint, FastAPI import smoke, no-GPU pytest lane
  (analyze / timemap / tempo / accuracy-threshold / synth-4stem)
* **frontend** — ESLint on changed components, vite build, Playwright
  harness check
* **accuracy** — runs `test_accuracy_thresholds.py` + the synth 4-stem
  smoke suite; fails when measured accuracy is below the documented
  minimum
* **a11y** — boots the Vite dev server, drives `@axe-core/playwright`
  against Landing and `/app`, fails on any `serious` / `critical` WCAG
  violation (`frontend/e2e/a11y.spec.js`). Moderate/minor findings are
  logged but do not gate yet; tighten the threshold once outstanding
  issues are cleared.

For a release tag:
1. Bump `RECHORD_RELEASE` in deploy env.
2. Run `scripts/run_accuracy_suite.py` locally with `--no-real` to
   pre-check the synth gate; full real-world gate runs in nightly CI.
3. Tag the commit; CI runs the full lane; deploy on green.

---

## 5. Observability — what to watch in prod

`job.meta.backend_summary` is the single source of truth per job:

```jsonc
{
  "backends_used": [
    {"stage": "separate",    "backend": "mdx23c_instvoc_hq+bs_roformer_1297+…",
     "level": "sota", "note": "4-model ensemble (weighted_mag)"},
    {"stage": "key_detect",  "backend": "madmom_cnn", "level": "sota"},
    {"stage": "chord_detect","backend": "crema",      "level": "sota",
     "note": "refine chain: crema+theory+llm"}
  ],
  "fallbacks": [],
  "install_hints": []
}
```

Alert on any of:
* `backend_summary.fallbacks` non-empty (machine is missing SOTA deps)
* `quality_grade` ∈ {D, E} (separation failure)
* `lufs_error_db` > 1.5 (loudness target missed)
* `true_peak_dbtp_after` > -0.5 (inter-sample clipping)
* `chord_bass_check.downgraded` > 30% (slash-chord hallucination spike)

These are all reachable via `GET /jobs/:id` and the existing WebSocket
progress stream.
