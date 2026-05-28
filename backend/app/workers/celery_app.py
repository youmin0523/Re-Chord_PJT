"""Celery worker (Phase B SaaS).

Phase A: queue is an in-process asyncio task pool (core/queue.py).
Phase B: replace with Celery + Redis so multiple worker containers
share the load and survive restarts.

This module is only imported when ``CELERY_BROKER_URL`` is set in env;
the API still calls ``get_queue().submit(job_id)`` which detects the
mode at runtime. Adding a worker container in docker-compose runs:

    celery -A backend.app.workers.celery_app worker -l info -c 2

Phase A devs never need this file.
"""

from __future__ import annotations

import os


_BROKER = os.environ.get("CELERY_BROKER_URL")
_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", _BROKER)


if _BROKER:
    try:
        from celery import Celery
    except ImportError as e:
        raise RuntimeError(
            "celery not installed. Add `celery[redis]` to your deploy image."
        ) from e

    app = Celery(
        "rechord",
        broker=_BROKER,
        backend=_BACKEND,
        # Phase B persisted-job knobs:
        broker_connection_retry_on_startup=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,           # one heavy job at a time
        result_expires=3600 * 24 * 7,           # keep results 7 days
    )

    @app.task(name="rechord.run_job", bind=True, max_retries=2)
    def run_job_task(self, job_id: str):
        """Pull the job from the DB by id, then execute the orchestrator.

        Phase A's orchestrator works on the in-memory ``registry.get(job_id)``;
        in Phase B the same orchestrator gets adapted to read the row from
        PostgreSQL via ``backend.app.db.repository``. The work below is the
        adapter — we lazy-import to keep Phase A devs unaffected.
        """
        import asyncio
        from ..core.jobs import registry
        from .orchestrator import run_job
        job = registry.get(job_id)
        if job is None:
            return {"ok": False, "reason": "job not found"}
        try:
            asyncio.run(run_job(job))
            return {"ok": True, "job_id": job_id}
        except Exception as e:                    # Celery retry
            raise self.retry(exc=e, countdown=15) from e
else:
    # Phase A: no broker → no Celery app exported. Importing the module is
    # still safe (used by docker-compose env probing).
    app = None
