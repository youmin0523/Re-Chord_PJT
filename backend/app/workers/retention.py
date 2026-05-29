"""PIPA-mandated data retention enforcement.

`docs/legal/privacy_policy.md` §3 commits to:

  * Uploaded audio (raw)     → 30 days
  * Separated stems / output → 30 days
  * Job metadata (DB row)    → 1 year
  * Chat session logs        → 1 year
  * Access logs (IP/UA)      → 3 months

This module implements the enforcement. It runs in two modes:

  * **Celery beat** (`celery_app.beat_schedule`) — production. Runs once
    per day at 03:00 UTC. Each task is idempotent and chunks its work so
    a missed day catches up on the next run.
  * **Background loop** (`start_background_retention()`) — Phase A /
    local dev without Celery. An asyncio task scheduled from FastAPI's
    lifespan; same task functions, same idempotency.

Either way, the *retention windows* are env-configurable so we can
shorten them for tests or extend during incidents.

The destructive ops touch DB rows and disk artifacts. Each task:
  1. emits a structured `log.info("retention.<task> start ...")` line
  2. does the work in batches of `RETENTION_BATCH`
  3. emits `retention.<task> done removed=N freed_bytes=M`
  4. captures any exception via `core.observability.capture_exception`

If the env var `RECHORD_DISABLE_RETENTION=1` is set, every entrypoint
short-circuits as a no-op (useful for first-week launches where the
team wants nothing auto-deleted while validating the platform).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.observability import capture_exception
from ..db.session import database_url, get_session


log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────

_AUDIO_DAYS    = int(os.environ.get("RECHORD_RETAIN_AUDIO_DAYS",   "30"))
_JOB_DAYS      = int(os.environ.get("RECHORD_RETAIN_JOB_DAYS",     "365"))
_CHAT_DAYS     = int(os.environ.get("RECHORD_RETAIN_CHAT_DAYS",    "365"))
_ACCESS_DAYS   = int(os.environ.get("RECHORD_RETAIN_ACCESS_DAYS",  "90"))
_BATCH         = int(os.environ.get("RECHORD_RETENTION_BATCH",    "500"))
_INTERVAL_SEC  = int(os.environ.get("RECHORD_RETENTION_INTERVAL_SEC", "86400"))
_DISABLED      = os.environ.get("RECHORD_DISABLE_RETENTION", "").strip() in ("1", "true", "yes")


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# ── Filesystem artifacts (uploads / stems / output) ──────────────


def purge_old_artifacts(max_age_days: int = _AUDIO_DAYS) -> dict:
    """Delete on-disk artifacts older than ``max_age_days``.

    Targets data/uploads, data/stems, data/output, data/work. Returns a
    summary dict so the caller can log it / surface in /ops.
    """
    if _DISABLED:
        log.info("retention.artifacts disabled (RECHORD_DISABLE_RETENTION=1)")
        return {"disabled": True, "files_removed": 0, "bytes_freed": 0}

    from ..config import settings
    from ..core.ops import cleanup_old_artifacts

    started = time.perf_counter()
    targets = [
        settings.data_dir / "uploads",
        settings.stems_dir,
        settings.output_dir,
        settings.work_dir,
    ]
    log.info("retention.artifacts start max_age_days=%d targets=%d", max_age_days, len(targets))
    try:
        res = cleanup_old_artifacts(
            targets,
            max_age_hours=max_age_days * 24.0,
            dry_run=False,
        )
        elapsed = time.perf_counter() - started
        log.info(
            "retention.artifacts done removed=%d freed_bytes=%d elapsed_sec=%.2f",
            res.files_removed, res.bytes_freed, elapsed,
        )
        return {
            "files_removed": res.files_removed,
            "bytes_freed":   res.bytes_freed,
            "elapsed_sec":   round(elapsed, 2),
            "sample":        list(res.paths[:5]),
        }
    except Exception as e:
        log.exception("retention.artifacts failed")
        capture_exception(e, stage="retention_artifacts")
        return {"error": repr(e), "files_removed": 0, "bytes_freed": 0}


# ── DB rows (jobs / chat / access logs) ───────────────────────────


async def purge_old_jobs(max_age_days: int = _JOB_DAYS) -> dict:
    """Delete ``jobs`` rows finished more than ``max_age_days`` ago."""
    if _DISABLED:
        return {"disabled": True, "removed": 0}
    if not database_url():
        log.info("retention.jobs skipped (no DATABASE_URL)")
        return {"skipped": True, "removed": 0}

    from sqlalchemy import delete
    from ..db.models import Job

    cutoff = _cutoff(max_age_days)
    log.info("retention.jobs start cutoff=%s", cutoff.isoformat())
    removed = 0
    try:
        async with get_session() as session:
            # Batched delete so a huge backlog doesn't lock the table.
            while True:
                # SQLAlchemy 2.x doesn't support LIMIT on a DELETE in
                # portable SQL; we select ids in chunks and then delete.
                from sqlalchemy import select
                ids = (await session.scalars(
                    select(Job.id)
                    .where(Job.finished_at != None)  # noqa: E711
                    .where(Job.finished_at < cutoff)
                    .limit(_BATCH)
                )).all()
                if not ids:
                    break
                await session.execute(delete(Job).where(Job.id.in_(ids)))
                await session.commit()
                removed += len(ids)
                if len(ids) < _BATCH:
                    break
        log.info("retention.jobs done removed=%d", removed)
        return {"removed": removed, "cutoff": cutoff.isoformat()}
    except Exception as e:
        log.exception("retention.jobs failed")
        capture_exception(e, stage="retention_jobs")
        return {"error": repr(e), "removed": removed}


async def purge_old_chat(max_age_days: int = _CHAT_DAYS) -> dict:
    """Delete chat conversations whose last update is older than the window.

    Deleting the conversation cascades to messages via ondelete=CASCADE.
    """
    if _DISABLED:
        return {"disabled": True, "removed": 0}
    if not database_url():
        log.info("retention.chat skipped (no DATABASE_URL)")
        return {"skipped": True, "removed": 0}

    from sqlalchemy import delete, select
    from ..db.models import ChatConversation

    cutoff = _cutoff(max_age_days)
    log.info("retention.chat start cutoff=%s", cutoff.isoformat())
    removed = 0
    try:
        async with get_session() as session:
            while True:
                ids = (await session.scalars(
                    select(ChatConversation.id)
                    .where(ChatConversation.updated_at < cutoff)
                    .limit(_BATCH)
                )).all()
                if not ids:
                    break
                await session.execute(
                    delete(ChatConversation).where(ChatConversation.id.in_(ids))
                )
                await session.commit()
                removed += len(ids)
                if len(ids) < _BATCH:
                    break
        log.info("retention.chat done removed=%d", removed)
        return {"removed": removed, "cutoff": cutoff.isoformat()}
    except Exception as e:
        log.exception("retention.chat failed")
        capture_exception(e, stage="retention_chat")
        return {"error": repr(e), "removed": removed}


# Access logs aren't materialised in our DB (Cloud Run / nginx own them);
# this is a stub so the orchestrator can call it uniformly. The retention
# is documented in privacy_policy.md §3 and enforced by the log
# aggregator's retention policy (Loki / CloudWatch / Stackdriver).
async def purge_old_access_logs(max_age_days: int = _ACCESS_DAYS) -> dict:
    return {
        "skipped":  True,
        "note":     "Access logs are retained by the log aggregator. "
                    f"Configure your sink to expire entries older than "
                    f"{max_age_days} days (privacy_policy.md §3).",
        "removed":  0,
    }


# ── Aggregate runner ─────────────────────────────────────────────


async def run_retention_once() -> dict:
    """Run every retention task one time. Called by both Celery beat and
    the in-process background loop."""
    return {
        "ran_at":   datetime.now(timezone.utc).isoformat(),
        "artifacts": purge_old_artifacts(),
        "jobs":      await purge_old_jobs(),
        "chat":      await purge_old_chat(),
        "access":    await purge_old_access_logs(),
    }


# ── Phase A / Phase B without Celery: in-process loop ────────────


_loop_task: asyncio.Task | None = None


def start_background_retention(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Schedule a daily run of ``run_retention_once`` on the asyncio loop.

    Idempotent: a second call is a no-op. Designed to be called from
    FastAPI's lifespan on startup. Disabled when
    ``RECHORD_DISABLE_RETENTION=1``.
    """
    global _loop_task
    if _DISABLED:
        log.info("retention: background loop disabled (RECHORD_DISABLE_RETENTION=1)")
        return
    if _loop_task is not None and not _loop_task.done():
        return

    loop = loop or asyncio.get_event_loop()

    async def _loop() -> None:
        # First sweep 5 min after boot so cold-start isn't blocked.
        await asyncio.sleep(300)
        while True:
            try:
                await run_retention_once()
            except Exception as e:                       # pragma: no cover
                log.exception("retention loop iteration failed")
                capture_exception(e, stage="retention_loop")
            await asyncio.sleep(_INTERVAL_SEC)

    _loop_task = loop.create_task(_loop(), name="rechord.retention")
    log.info(
        "retention: background loop scheduled (interval=%ds, audio=%dd, jobs=%dd, chat=%dd)",
        _INTERVAL_SEC, _AUDIO_DAYS, _JOB_DAYS, _CHAT_DAYS,
    )


# ── Celery beat hooks ────────────────────────────────────────────


def register_celery_beat(celery_app) -> None:
    """Register the daily retention task on a Celery app instance.

    Idempotent. Called from ``workers/celery_app.py`` after Celery init.
    """
    if _DISABLED:
        log.info("retention: Celery beat skipped (RECHORD_DISABLE_RETENTION=1)")
        return

    @celery_app.task(name="rechord.run_retention")
    def _retention_task():                                # pragma: no cover
        return asyncio.run(run_retention_once())

    # 03:00 UTC daily — chosen so it doesn't overlap with peak Korean
    # worship-team usage (Sun morning KST ≈ Sat evening UTC).
    try:
        from celery.schedules import crontab               # type: ignore
        celery_app.conf.beat_schedule = {
            **getattr(celery_app.conf, "beat_schedule", {}),
            "rechord-retention-daily": {
                "task":     "rechord.run_retention",
                "schedule": crontab(hour=3, minute=0),
            },
        }
        log.info("retention: Celery beat registered (03:00 UTC daily)")
    except ImportError:
        log.warning("celery installed but `celery.schedules` missing — skipping beat schedule")
