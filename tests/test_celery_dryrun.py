"""Phase B Celery wiring smoke test.

Runs in the no-GPU CI lane: imports backend.app.workers.celery_app with a
fake broker URL, verifies the Celery app is constructed and the
``rechord.run_job`` task is registered. We don't actually connect to a
broker — we just confirm the module wires up correctly so a typo or stale
config doesn't ship to production unnoticed.

The Phase A "broker URL unset → app is None" path is also covered.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest


def _reload_celery_app():
    """Reload the worker module so env-var changes take effect.

    The module reads CELERY_BROKER_URL at import time, so plain re-import
    after `os.environ[...] = ...` is a no-op without an explicit reload.
    """
    mod_name = "backend.app.workers.celery_app"
    if mod_name in sys.modules:
        return importlib.reload(sys.modules[mod_name])
    return importlib.import_module(mod_name)


@pytest.fixture
def with_broker_env(monkeypatch):
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://fake:6379/1")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://fake:6379/2")
    yield


@pytest.fixture
def without_broker_env(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)
    yield


def test_celery_app_disabled_without_broker(without_broker_env):
    """Phase A: no broker URL → module imports cleanly, app is None."""
    mod = _reload_celery_app()
    assert mod.app is None, "Phase A should leave Celery uninitialised"


def test_celery_app_wires_when_broker_set(with_broker_env):
    """Phase B: broker URL set → Celery app exists with our knobs.

    We don't connect; we just inspect the configured app object. If
    celery isn't installed this test is skipped — CI installs it via
    the [saas] / explicit install line.
    """
    try:
        import celery  # noqa: F401
    except ImportError:
        pytest.skip("celery not installed in this env (Phase A dev)")

    mod = _reload_celery_app()
    assert mod.app is not None, "Phase B should build a Celery app"
    assert mod.app.conf.broker_url == "redis://fake:6379/1"
    assert mod.app.conf.task_acks_late is True
    assert mod.app.conf.worker_prefetch_multiplier == 1

    task_names = set(mod.app.tasks.keys())
    assert "rechord.run_job" in task_names, (
        f"run_job task missing from registry. Got: {sorted(task_names)[:10]}"
    )


def teardown_module():
    """Restore module state so other tests don't inherit our env mutations."""
    # Clear any cached env mutation so re-import picks up the real env.
    for k in ("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        os.environ.pop(k, None)
    if "backend.app.workers.celery_app" in sys.modules:
        importlib.reload(sys.modules["backend.app.workers.celery_app"])
