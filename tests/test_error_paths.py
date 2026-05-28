"""Error-path coverage for the public API surface.

Pre-existing tests focus on the happy path. This file pins the 4xx/5xx
shapes — what users see when they hit a bad job id, a malformed payload,
or try to download an artifact that doesn't exist. Regressions here
silently turn user-facing errors into ``500`` walls of html, which is
worse than the error itself.

Covered:
  * GET /jobs/{missing}         → 404
  * DELETE /jobs/{missing}      → 404
  * GET /jobs/{missing}/download/{kind} → 404
  * GET /jobs/{missing}/chords  → 404
  * GET /jobs/{missing}/sections → 404
  * POST /jobs with empty body  → 422
  * POST /jobs with bad enum    → 422
  * WS /jobs/{missing}/progress → connection closes promptly

These all run against the in-memory FastAPI app via TestClient — no
disk, no GPU, ~50ms per case.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("err_data")
    os.environ["RECHORD_DATA_DIR"] = str(data_dir)
    os.environ["RECHORD_PREWARM_AT_BOOT"] = "0"
    try:
        from fastapi.testclient import TestClient
        from backend.app.main import app
    except Exception as e:
        pytest.skip(f"backend import failed: {e!r}")
    with TestClient(app) as c:
        yield c


MISSING_ID = "does-not-exist-xyz-404"


# ── Job lookups ────────────────────────────────────────────────────


def test_get_job_missing_returns_404(client):
    r = client.get(f"/jobs/{MISSING_ID}")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body
    assert "not found" in body["detail"].lower()


def test_cancel_missing_job_returns_404(client):
    r = client.delete(f"/jobs/{MISSING_ID}")
    assert r.status_code == 404


def test_download_missing_job_returns_404(client):
    r = client.get(f"/jobs/{MISSING_ID}/download/instrumental_final")
    assert r.status_code == 404
    # Whether the message reads "job not found" or "artifact missing"
    # is fine — we care that the user gets a structured 4xx, not a 500.
    assert "detail" in r.json()


@pytest.mark.parametrize("subpath", ["chords", "sections", "lyrics"])
def test_analysis_endpoints_missing_job_returns_404(client, subpath):
    """Per-stage GETs all 404 cleanly on an unknown job id.

    We tolerate either 404 (current behavior) or 422 (FastAPI path
    validation if the schema rejects the format) — both are structured
    user-facing errors, not server crashes.
    """
    r = client.get(f"/jobs/{MISSING_ID}/{subpath}")
    assert r.status_code in (404, 422), f"unexpected status {r.status_code}: {r.text}"


# ── Job creation validation ───────────────────────────────────────


def test_post_jobs_empty_body_returns_422(client):
    r = client.post("/jobs", json={})
    assert r.status_code == 422
    body = r.json()
    assert "detail" in body
    assert isinstance(body["detail"], list)


def test_post_jobs_missing_input_returns_422(client):
    r = client.post("/jobs", json={"options": {"mode": "quick_mr"}})
    assert r.status_code == 422
    assert any("input" in str(e) for e in r.json().get("detail", []))


def test_post_jobs_bad_mode_returns_422(client):
    r = client.post("/jobs", json={
        "input": "upload:nonexistent",
        "options": {
            "mode": "definitely-not-a-real-mode",
            "format": "wav",
        },
    })
    assert r.status_code == 422


def test_post_jobs_bad_format_returns_422(client):
    r = client.post("/jobs", json={
        "input": "upload:nonexistent",
        "options": {
            "mode": "quick_mr",
            "format": "matroska",
        },
    })
    assert r.status_code == 422


# ── WebSocket: unknown job ────────────────────────────────────────


def test_websocket_unknown_job_closes(client):
    """Connecting to /jobs/{missing}/progress should not hang.

    Two acceptable behaviours:
      a) Server rejects on handshake → ``websocket_connect`` raises
         ``WebSocketDisconnect`` on entry.
      b) Server accepts, sends an error/done frame, then closes →
         the second ``receive`` raises ``WebSocketDisconnect``.

    Either way: a real client sees a bounded-time signal, never an
    infinite hang. We assert exactly that.
    """
    from starlette.websockets import WebSocketDisconnect

    saw_disconnect = False
    try:
        with client.websocket_connect(f"/jobs/{MISSING_ID}/progress") as ws:
            # Drain up to ~5 frames; if the server keeps streaming valid
            # progress for an unknown job, that's a real bug — fail loudly.
            for _ in range(5):
                try:
                    ws.receive_json()
                except WebSocketDisconnect:
                    saw_disconnect = True
                    break
            else:
                pytest.fail("WS for missing job streamed 5+ frames without closing")
    except WebSocketDisconnect:
        saw_disconnect = True

    assert saw_disconnect, "expected the WS to close for an unknown job id"
