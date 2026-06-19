"""Per-IP + global rate limiting for the internet-exposed API.

The backend is public via the Cloudflare tunnel, so the chat (OpenAI $$$)
and job (single shared GPU) endpoints need abuse/cost guards on top of the
existing per-session chat limiter — a session is free to mint, so a
per-session cap alone is trivially bypassed. Cloudflare forwards the real
visitor IP in ``CF-Connecting-IP``.

All caps are env-configurable (0 = disabled). In-memory, single-host
(Phase A); Phase B would back this with Redis.
"""

from __future__ import annotations

import os
import threading
import time

from fastapi import Request


def client_ip(request: Request) -> str:
    """Best-effort real client IP. Trusts Cloudflare's header first (the
    tunnel sets it), then X-Forwarded-For, then the socket peer."""
    h = request.headers
    cf = h.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = h.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _int_env(name: str, default: int) -> int:
    try:
        v = (os.environ.get(name) or "").strip()
        return int(v) if v else default
    except ValueError:
        return default


class FixedWindowLimiter:
    """Fixed-window counter. ``allow(key)`` consumes one slot and returns
    ``(ok, retry_after_sec)``. ``limit <= 0`` disables it (always ok)."""

    __slots__ = ("limit", "window", "_buckets", "_lock")

    def __init__(self, limit: int, window_sec: float) -> None:
        self.limit = int(limit)
        self.window = float(window_sec)
        self._buckets: dict[str, list[float]] = {}  # key -> [count, reset_at]
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        if self.limit <= 0:
            return True, 0.0
        now = time.time()
        with self._lock:
            b = self._buckets.get(key)
            if b is None or now >= b[1]:
                b = [0.0, now + self.window]
                self._buckets[key] = b
                if len(self._buckets) > 10000:  # opportunistic GC of stale keys
                    for k in [k for k, v in self._buckets.items() if v[1] <= now]:
                        self._buckets.pop(k, None)
            if b[0] < self.limit:
                b[0] += 1
                return True, 0.0
            return False, max(0.0, b[1] - now)


_MIN, _HOUR, _DAY = 60.0, 3600.0, 86400.0

# Chat — OpenAI cost guard: per-IP/min + a global/day ceiling (the wallet stop).
chat_ip_limiter = FixedWindowLimiter(_int_env("RATELIMIT_CHAT_PER_MIN_PER_IP", 30), _MIN)
chat_global_daily = FixedWindowLimiter(_int_env("RATELIMIT_CHAT_PER_DAY_GLOBAL", 1000), _DAY)

# Jobs — single-GPU guard: per-IP/hour + a global/day ceiling.
jobs_ip_limiter = FixedWindowLimiter(_int_env("RATELIMIT_JOBS_PER_HOUR_PER_IP", 20), _HOUR)
jobs_global_daily = FixedWindowLimiter(_int_env("RATELIMIT_JOBS_PER_DAY_GLOBAL", 200), _DAY)
