"""Pin the job-state disk persistence (restart recovery).

  * A terminal job persisted to disk is reloaded by a fresh registry.
  * A job that was mid-flight (running/queued) when persisted is
    reloaded as 'error' with a clear message.
  * Restore is idempotent and never duplicates already-loaded jobs.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture()
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("RECHORD_DATA_DIR", str(tmp_path))
    # Fresh import of settings + a brand-new registry instance bound to tmp.
    from backend.app.core.jobs import JobRegistry, Job, JobOptions
    reg = JobRegistry()
    # Force the persist dir to the tmp path's jobs/ subdir.
    reg._persist_dir = tmp_path / "jobs"
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    return reg, Job, JobOptions, tmp_path


def test_persist_and_restore_done_job(isolated_registry):
    reg, Job, JobOptions, tmp_path = isolated_registry
    job = Job(id="done-001", input="upload:x", options=JobOptions())
    job.status = "done"
    job.stage = "done"
    job.progress = 1.0
    job.artifacts["instrumental_final"] = "/data/output/done-001/instrumental.wav"
    job.meta["key_name"] = "G major"
    reg.persist(job)

    # Fresh registry, same dir → should reload the done job.
    from backend.app.core.jobs import JobRegistry
    reg2 = JobRegistry()
    reg2._persist_dir = tmp_path / "jobs"
    n = reg2.restore_from_disk()
    assert n == 1
    restored = reg2.get("done-001")
    assert restored is not None
    assert restored.status == "done"
    assert restored.artifacts["instrumental_final"].endswith("instrumental.wav")
    assert restored.meta["key_name"] == "G major"


def test_midflight_job_restored_as_error(isolated_registry):
    reg, Job, JobOptions, tmp_path = isolated_registry
    job = Job(id="run-002", input="upload:y", options=JobOptions())
    job.status = "running"
    job.stage = "separate"
    job.progress = 0.4
    reg.persist(job)

    from backend.app.core.jobs import JobRegistry
    reg2 = JobRegistry()
    reg2._persist_dir = tmp_path / "jobs"
    reg2.restore_from_disk()
    restored = reg2.get("run-002")
    assert restored is not None
    assert restored.status == "error"
    assert restored.error  # has a message
    assert "재시작" in restored.error or "restart" in restored.error.lower()


def test_restore_is_idempotent(isolated_registry):
    reg, Job, JobOptions, tmp_path = isolated_registry
    job = Job(id="done-003", input="upload:z", options=JobOptions())
    job.status = "done"
    reg.persist(job)

    from backend.app.core.jobs import JobRegistry
    reg2 = JobRegistry()
    reg2._persist_dir = tmp_path / "jobs"
    n1 = reg2.restore_from_disk()
    n2 = reg2.restore_from_disk()      # second call — already loaded
    assert n1 == 1
    assert n2 == 0
    assert len(reg2._jobs) == 1


def test_persist_survives_options_roundtrip(isolated_registry):
    reg, Job, JobOptions, tmp_path = isolated_registry
    job = Job(id="done-004", input="upload:w",
              options=JobOptions(mode="pro", make_score=True))
    job.status = "done"
    reg.persist(job)

    from backend.app.core.jobs import JobRegistry
    reg2 = JobRegistry()
    reg2._persist_dir = tmp_path / "jobs"
    reg2.restore_from_disk()
    restored = reg2.get("done-004")
    assert restored.options.mode == "pro"
    assert restored.options.make_score is True
