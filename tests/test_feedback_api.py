"""End-to-end test for the /feedback endpoint family."""

from __future__ import annotations

import os
import shutil

import pytest


@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("fb_data")
    os.environ["RECHORD_DATA_DIR"] = str(data_dir)
    os.environ["RECHORD_PREWARM_AT_BOOT"] = "0"
    try:
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.core.jobs import Job, JobOptions, registry
    except Exception as e:
        pytest.skip(f"backend import failed: {e!r}")

    # Seed a job in the in-memory registry so /feedback can reference it.
    job = Job(id="testjob-001", input="upload:none", options=JobOptions())
    registry._jobs[job.id] = job

    with TestClient(app) as c:
        yield c, job
    registry._jobs.pop(job.id, None)
    shutil.rmtree(data_dir, ignore_errors=True)


def test_submit_minimal_feedback(app_client):
    c, job = app_client
    r = c.post("/feedback", json={
        "job_id": job.id,
        "ratings": {"separation": 4, "overall": 4},
        "notes": "MR is mostly clean but some residual vocals at chorus.",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["feedback_id"].endswith(job.id[:8])


def test_submit_rejects_unknown_job(app_client):
    c, _ = app_client
    r = c.post("/feedback", json={
        "job_id": "does-not-exist",
        "ratings": {"overall": 3},
    })
    assert r.status_code == 404


def test_submit_rejects_out_of_range_rating(app_client):
    c, job = app_client
    r = c.post("/feedback", json={
        "job_id": job.id,
        "ratings": {"overall": 7},
    })
    assert r.status_code == 422


def test_submit_rejects_empty_body(app_client):
    c, job = app_client
    r = c.post("/feedback", json={
        "job_id": job.id,
        "ratings": {},
        "notes": "",
    })
    assert r.status_code == 422


def test_summary_aggregates_responses(app_client):
    c, job = app_client
    # Add a second submission so we can verify aggregation.
    c.post("/feedback", json={
        "job_id": job.id,
        "ratings": {"separation": 5, "score": 3},
        "notes": "Score dynamics suddenly applied — love it.",
    })
    r = c.get("/feedback/summary")
    assert r.status_code == 200
    summary = r.json()
    assert summary["total_responses"] >= 2
    assert "separation" in summary["per_category"]
    sep = summary["per_category"]["separation"]
    assert sep["n"] >= 2
    assert 1 <= sep["avg"] <= 5
    # Histogram sum equals n.
    assert sum(sep["hist"]) == sep["n"]


def test_summary_includes_recent_notes(app_client):
    c, _ = app_client
    r = c.get("/feedback/summary")
    summary = r.json()
    notes = [t["notes"] for t in summary.get("top_issues", [])]
    assert any("Score dynamics" in n or "residual" in n for n in notes)
