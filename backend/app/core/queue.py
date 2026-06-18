"""Async in-process job queue. Phase B will swap for Celery+Redis."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Awaitable, Callable

from .jobs import Job, registry


JobRunner = Callable[[Job], Awaitable[None]]


class JobQueue:
    """Single-consumer queue. MAX_CONCURRENT_JOBS=1 in Phase A.

    Tracks the currently-running task per job_id so ``cancel(job_id)``
    can stop a job mid-flight. The orchestrator catches CancelledError
    and marks the job as ``cancelled``.
    """

    def __init__(self, runner: JobRunner, concurrency: int = 1,
                 max_pending: int = 0) -> None:
        # Bounded queue so a flood of submissions can't blow up memory.
        # max_pending=0 → unbounded (legacy). The API layer should catch
        # QueueFull and return HTTP 429.
        import os
        if max_pending <= 0:
            try:
                max_pending = int(os.environ.get("RECHORD_MAX_PENDING_JOBS", "200"))
            except ValueError:
                max_pending = 200
        self._max_pending = max(0, max_pending)
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._max_pending)
        self._runner = runner
        self._concurrency = concurrency
        self._workers: list[asyncio.Task[None]] = []
        self._stopped = False
        # job_id → asyncio.Task running it, for mid-flight cancellation.
        self._active: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        # Reset the stop flag so a queue that was previously stopped (e.g. a
        # lifespan teardown followed by a fresh boot — every TestClient does
        # this, and some ASGI servers re-run lifespan on reload) comes back
        # to life. Without this the new workers would see ``_stopped=True``
        # and exit immediately, silently wedging every job. (Was the root
        # cause of the e2e test failing only inside the full suite.)
        self._stopped = False
        if self._workers:
            return
        for i in range(self._concurrency):
            t = asyncio.create_task(self._worker_loop(i), name=f"job-worker-{i}")
            self._workers.append(t)

    async def stop(self) -> None:
        self._stopped = True
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await w
        self._workers.clear()

    def submit(self, job_id: str) -> None:
        """Enqueue a job. Raises asyncio.QueueFull when the backlog is at
        capacity — the API layer translates that into HTTP 429 so the
        client can retry later instead of the server OOMing."""
        self._queue.put_nowait(job_id)

    def pending_count(self) -> int:
        return self._queue.qsize()

    def capacity(self) -> int:
        return self._max_pending

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued or running job. Returns True if the cancel signal
        was successfully delivered.

        Three cases:
          1. job is currently running   → cancel the task; orchestrator
             catches CancelledError and marks status=cancelled.
          2. job is queued but not yet picked up → mark it cancelled in
             the registry so the worker skips it when it polls.
          3. job not found / already done → return False.
        """
        job = registry.get(job_id)
        if job is None:
            return False
        if job.status in ("done", "error", "cancelled"):
            return False
        active = self._active.get(job_id)
        if active is not None and not active.done():
            active.cancel()
            return True
        # Queued but not running: flag in registry; worker picks up the flag.
        job.status = "cancelled"
        job.error = "cancelled before start"
        return True

    async def _worker_loop(self, worker_idx: int) -> None:
        while not self._stopped:
            try:
                job_id = await self._queue.get()
            except asyncio.CancelledError:
                return
            job = registry.get(job_id)
            if job is None:
                self._queue.task_done()
                continue
            # Honour cancellation requested while queued.
            if job.status == "cancelled":
                self._queue.task_done()
                continue
            task = asyncio.current_task()
            if task is not None:
                self._active[job_id] = task
            try:
                await self._runner(job)
            except asyncio.CancelledError:
                job.status = "cancelled"
                # Eat the cancellation so the worker loop survives — we
                # only wanted to cancel this one job.
            except Exception as e:
                job.status = "error"
                job.error = repr(e)
            finally:
                self._active.pop(job_id, None)
                self._queue.task_done()


_global_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    assert _global_queue is not None, "JobQueue not initialized; call init_queue() in startup"
    return _global_queue


def init_queue(runner: JobRunner, concurrency: int = 1,
               max_pending: int = 0) -> JobQueue:
    """Create the process-wide job queue. Always builds a *fresh* queue so
    its internal ``asyncio.Queue`` binds to the event loop that is running
    at startup. Reusing a previous instance across boots (every TestClient,
    or an ASGI lifespan re-run) leaves the queue bound to a dead loop —
    workers then raise "Queue is bound to a different event loop" and every
    job hangs in ``queued``. Lifespan startup calls this exactly once per
    boot, so replacing the global here is correct in production too."""
    global _global_queue
    _global_queue = JobQueue(runner, concurrency=concurrency,
                             max_pending=max_pending)
    return _global_queue
