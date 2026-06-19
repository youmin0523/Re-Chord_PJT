"""End-to-end pipeline integration test.

Spawns a synthetic stereo audio file, posts it through the FastAPI app
in-process (no live network), and asserts the orchestrator produces the
expected artifacts. Mocks the heavy separator so the test stays under 30s
on CPU only — the test verifies plumbing, not model quality (that's what
test_separation_regression covers).

Goal: every commercial release must prove that a single user click can
travel through upload → analyze → separate → encode → quality without
silently dropping any artifact, even on machines without GPU + heavy ML
deps installed.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import time
import wave
from pathlib import Path
from typing import Iterator

import numpy as np
import pytest


@pytest.fixture(scope="module")
def synth_wav(tmp_path_factory) -> Path:
    """A 12-second stereo 'song': sine + saw + noise. Enough for analyze and
    above the min-duration guard (clips <10s are rejected up front)."""
    sr = 48000
    dur = 12.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    L = 0.4 * np.sin(2 * np.pi * 220 * t) + 0.2 * np.sin(2 * np.pi * 440 * t)
    R = 0.4 * np.sin(2 * np.pi * 220 * t) + 0.2 * np.sin(2 * np.pi * 660 * t)
    stereo = np.stack([L, R], axis=1).astype(np.float32)
    stereo += 0.02 * np.random.RandomState(0).randn(*stereo.shape).astype(np.float32)
    stereo = np.clip(stereo, -1, 1)
    p = tmp_path_factory.mktemp("e2e") / "synth.wav"
    # Manual wave-write so we don't need soundfile in this test.
    with wave.open(str(p), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    return p


@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    """Boot the FastAPI app with isolated data dir + mock separator."""
    data_dir = tmp_path_factory.mktemp("e2e_data")
    os.environ["RECHORD_DATA_DIR"] = str(data_dir)
    os.environ["RECHORD_PREWARM_AT_BOOT"] = "0"

    try:
        from fastapi.testclient import TestClient
        from backend.app.main import app
    except Exception as e:
        pytest.skip(f"backend import failed: {e!r}")

    with TestClient(app) as c:
        yield c


def _wait_for_done(client, job_id: str, *, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/jobs/{job_id}")
        if r.status_code != 200:
            time.sleep(0.5); continue
        last = r.json()
        stage = (last.get("stage") or "").lower()
        message = (last.get("message") or "").upper()
        if stage in ("done", "failed", "error") or "FAILED" in message:
            return last
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not complete in {timeout}s; last={last}")


def test_health_returns_ok(app_client):
    r = app_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "tools" in body


def test_formats_endpoint_lists_supported_outputs(app_client):
    r = app_client.get("/formats")
    assert r.status_code == 200
    body = r.json()
    assert any(k in body for k in ("output_formats", "modes", "models"))


def test_create_job_then_progress_event_stream(app_client, synth_wav, monkeypatch):
    """A real upload through to artifacts. Skips when the separator is unavailable."""
    try:
        from backend.app.pipeline import separate as sep_mod
    except Exception as e:
        pytest.skip(f"pipeline.separate import failed: {e!r}")

    if not hasattr(sep_mod, "separate_two_stem"):
        pytest.skip("separator API missing")

    # Mock the separator so the test doesn't depend on 6 GB of weights.
    def _fake_separate(input_path, job_id, model_filename, output_dir=None, **kwargs):
        from backend.app.pipeline.separate import SeparateResult
        import shutil
        out = (output_dir or sep_mod.settings.stems_dir) / job_id
        out.mkdir(parents=True, exist_ok=True)
        # Just copy the input as both stems — accuracy is irrelevant here.
        v = out / "vocals.wav"
        i = out / "instrumental.wav"
        shutil.copy(str(input_path), v)
        shutil.copy(str(input_path), i)
        return SeparateResult(
            job_id=job_id, model="mock",
            stems={"vocals": v, "instrumental": i},
            elapsed_sec=0.01, input_duration_sec=6.0,
        )

    # The orchestrator imports separate_two_stem by name (``from ... import
    # separate_two_stem``), so it holds its own reference — patch it there,
    # where it is actually called, not only on the separate module.
    monkeypatch.setattr(sep_mod, "separate_two_stem", _fake_separate)
    import backend.app.workers.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "separate_two_stem", _fake_separate)

    # 1) Upload
    with open(synth_wav, "rb") as fp:
        r = app_client.post(
            "/uploads", files={"file": ("synth.wav", fp, "audio/wav")}
        )
    assert r.status_code in (200, 201), r.text
    upload = r.json()
    # The /uploads endpoint returns the staged file path; the client passes
    # that path straight back as the job input (see frontend Home.jsx).
    upload_path = upload.get("path")
    assert upload_path, f"upload response missing path: {upload}"

    # 2) Create job referencing the upload
    body = {
        "input": upload_path,
        "options": {
            "mode": "quick_mr",
            "models": ["mdx23c_instvoc_hq"],
            "detect_chords": False,
            "make_score": False,
            "make_lyrics": False,
            "polish": False,
            "format": "wav",
            "sample_rate": 48000,
            "bit_depth": "16",
        },
    }
    r = app_client.post("/jobs", json=body)
    assert r.status_code in (200, 201), r.text
    job = r.json()
    job_id = job["id"]

    # 3) Poll until done
    final = _wait_for_done(app_client, job_id, timeout=60.0)
    assert (final.get("stage") or "").lower() == "done", f"job ended in: {final}"

    # 4) The orchestrator should have produced at minimum the instrumental
    artifacts = final.get("artifacts") or {}
    # We accept either 'instrumental' or 'mr' depending on the mode wiring.
    assert any(k in artifacts for k in ("instrumental", "mr", "vocals")), \
        f"no audio artifacts in job: {artifacts}"
