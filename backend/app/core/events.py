"""Per-job progress event pub/sub.

Each job has an asyncio.Queue per active subscriber (WebSocket connection).
Publishers (the worker) push events; subscribers receive them.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class JobEvent:
    job_id: str
    type: str                       # "stage" | "progress" | "log" | "done" | "error"
    stage: str = ""                 # ingest | decode | separate | analyze | transform | encode | done
    progress: float = 0.0           # 0.0 ~ 1.0
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class EventBus:
    """Per-job fan-out broadcast for progress events.

    Stores a small ring buffer so a late subscriber (e.g. browser refresh)
    can replay the last N events on connect.
    """

    def __init__(self, buffer_size: int = 200) -> None:
        self._subs: dict[str, list[asyncio.Queue[JobEvent]]] = {}
        self._history: dict[str, list[JobEvent]] = {}
        self._buf = buffer_size
        self._lock = asyncio.Lock()

    async def publish(self, event: JobEvent) -> None:
        async with self._lock:
            hist = self._history.setdefault(event.job_id, [])
            hist.append(event)
            if len(hist) > self._buf:
                del hist[: len(hist) - self._buf]
            queues = list(self._subs.get(event.job_id, ()))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def subscribe(self, job_id: str) -> tuple[asyncio.Queue[JobEvent], list[JobEvent]]:
        q: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=1024)
        async with self._lock:
            self._subs.setdefault(job_id, []).append(q)
            replay = list(self._history.get(job_id, ()))
        return q, replay

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue[JobEvent]) -> None:
        async with self._lock:
            qs = self._subs.get(job_id, [])
            if queue in qs:
                qs.remove(queue)
            if not qs and job_id in self._subs:
                del self._subs[job_id]


bus = EventBus()
