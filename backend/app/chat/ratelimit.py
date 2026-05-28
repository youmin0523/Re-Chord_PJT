"""Per-session token-bucket rate limiter for the chat endpoint.

In-memory only — fine for Phase A single-process deployments. Phase B will
swap this for a Redis-backed bucket without touching the call sites.

Config (from settings):
  chat_rate_limit_per_minute: refill rate (tokens / minute)
  chat_rate_limit_burst:      maximum tokens the bucket can hold
A value of 0 for ``chat_rate_limit_per_minute`` disables the limit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from ..config import settings


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class _RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = Lock()

    def check(self, session_id: str) -> tuple[bool, float]:
        """Try to consume 1 token for ``session_id``.

        Returns ``(allowed, retry_after_seconds)``. When ``allowed`` is
        True the bucket is decremented; when False the caller should
        return 429 with the suggested retry delay.
        """
        per_min = settings.chat_rate_limit_per_minute
        burst = max(1, settings.chat_rate_limit_burst)
        if per_min <= 0:
            return True, 0.0
        refill_per_sec = per_min / 60.0
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(session_id)
            if b is None:
                # Start full so the first message is always allowed.
                b = _Bucket(tokens=float(burst), last_refill=now)
                self._buckets[session_id] = b
            # Refill based on elapsed wall time.
            elapsed = max(0.0, now - b.last_refill)
            b.tokens = min(float(burst), b.tokens + elapsed * refill_per_sec)
            b.last_refill = now
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return True, 0.0
            # Need (1 - tokens) more — how long until that's refilled?
            needed = 1.0 - b.tokens
            wait = needed / refill_per_sec if refill_per_sec > 0 else 60.0
            return False, max(0.5, wait)

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._buckets.pop(session_id, None)


_LIMITER: _RateLimiter | None = None


def get_limiter() -> _RateLimiter:
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = _RateLimiter()
    return _LIMITER


__all__ = ["get_limiter"]
