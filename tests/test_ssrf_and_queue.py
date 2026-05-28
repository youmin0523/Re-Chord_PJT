"""Pin the SSRF URL guard + the bounded queue behaviour."""

from __future__ import annotations

import asyncio

import pytest

from backend.app.pipeline.ingest import validate_url_safety


@pytest.mark.parametrize("url", [
    "http://localhost/admin",
    "http://127.0.0.1:8080/",
    "https://169.254.169.254/latest/meta-data/",   # AWS metadata
    "http://metadata.google.internal/",
    "http://0.0.0.0/",
    "http://10.0.0.5/internal",
    "http://192.168.1.1/router",
    "http://[::1]/",                                # IPv6 loopback
])
def test_blocked_private_urls_raise(url):
    with pytest.raises(ValueError):
        validate_url_safety(url)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "https://soundcloud.com/artist/track",
])
def test_public_urls_pass(url):
    # Should not raise (these resolve to public IPs or DNS may fail →
    # we let it pass for yt-dlp to handle).
    validate_url_safety(url)


def test_override_allows_private(monkeypatch):
    monkeypatch.setenv("RECHORD_ALLOW_PRIVATE_URLS", "1")
    # With the override, an internal media server URL is allowed.
    validate_url_safety("http://192.168.1.50/media/song.mp3")


def test_empty_host_raises():
    with pytest.raises(ValueError):
        validate_url_safety("http:///nohost")


# ── bounded queue ──────────────────────────────────────────────────

def test_queue_rejects_when_full():
    async def _dummy_runner(job):
        await asyncio.sleep(0)

    async def _run():
        from backend.app.core.queue import JobQueue
        q = JobQueue(_dummy_runner, concurrency=1, max_pending=3)
        # Do NOT start workers — so submitted jobs stay pending.
        q.submit("j1")
        q.submit("j2")
        q.submit("j3")
        assert q.pending_count() == 3
        assert q.capacity() == 3
        with pytest.raises(asyncio.QueueFull):
            q.submit("j4")          # 4th exceeds capacity

    asyncio.run(_run())


def test_queue_capacity_reported():
    async def _dummy_runner(job):
        await asyncio.sleep(0)

    async def _run():
        from backend.app.core.queue import JobQueue
        q = JobQueue(_dummy_runner, concurrency=1, max_pending=50)
        assert q.capacity() == 50
        assert q.pending_count() == 0

    asyncio.run(_run())
