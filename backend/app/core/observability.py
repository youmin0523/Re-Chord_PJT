"""Structured logging + Sentry hookup for Re:Chord backend.

Plain stdlib ``logging`` works fine for printf debugging but a SaaS-shaped
deployment needs:

  * machine-parseable JSON output (so Loki/Datadog/Cloudwatch can index
    job_id, stage, etc. without regex)
  * correlation between a user-facing error and the chain of pipeline
    log lines that led to it
  * automatic Sentry breadcrumbs and exception capture

This module wires those once at FastAPI startup. Configuration is
env-driven so Phase A devs don't need to think about it:

  RECHORD_LOG_FORMAT   = "json" | "text"    (default: "text")
  RECHORD_LOG_LEVEL    = standard names      (default: "INFO")
  SENTRY_DSN           = Sentry project DSN  (default: unset → Sentry off)
  RECHORD_ENV          = "dev" | "stage" | "prod" (default: "dev")

Usage:
    from .core.observability import setup_logging, get_logger
    setup_logging()
    log = get_logger(__name__)
    log.info("job started", job_id=job.id, stage="ingest")
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any


_INITIALISED = False


def _stdlib_level(name: str) -> int:
    return getattr(logging, name.upper(), logging.INFO)


def setup_logging() -> None:
    """One-shot configuration. Safe to call multiple times.

    When ``structlog`` is installed we route through it for JSON output
    + context binding. Without it we fall back to stdlib formatting so
    Phase A devs without the optional dep still get readable logs.
    """
    global _INITIALISED
    if _INITIALISED:
        return

    fmt = (os.environ.get("RECHORD_LOG_FORMAT") or "text").strip().lower()
    level = _stdlib_level(os.environ.get("RECHORD_LOG_LEVEL") or "INFO")

    # ── stdlib root logger configuration ────────────────────────────
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    if fmt == "json":
        handler.setFormatter(logging.Formatter(
            '{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s",'
            '"msg":"%(message)s"}'
        ))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root.addHandler(handler)

    # ── structlog (optional) ────────────────────────────────────────
    try:
        import structlog  # type: ignore
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ]
        if fmt == "json":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(level),
            cache_logger_on_first_use=True,
        )
    except ImportError:
        pass

    # ── Sentry (optional) ───────────────────────────────────────────
    dsn = (os.environ.get("SENTRY_DSN") or "").strip()
    if dsn:
        try:
            import sentry_sdk  # type: ignore
            from sentry_sdk.integrations.fastapi import FastApiIntegration  # type: ignore
            from sentry_sdk.integrations.logging import LoggingIntegration  # type: ignore
            sentry_sdk.init(
                dsn=dsn,
                environment=os.environ.get("RECHORD_ENV") or "dev",
                release=os.environ.get("RECHORD_RELEASE") or "0.3.0",
                traces_sample_rate=float(
                    os.environ.get("SENTRY_TRACES_SAMPLE_RATE") or "0.0"
                ),
                integrations=[
                    FastApiIntegration(),
                    LoggingIntegration(
                        level=logging.INFO, event_level=logging.ERROR,
                    ),
                ],
            )
        except ImportError:
            logging.getLogger(__name__).info(
                "SENTRY_DSN set but sentry-sdk not installed — "
                "run `uv pip install sentry-sdk[fastapi]` to enable."
            )
        except Exception as e:  # pragma: no cover — defensive
            logging.getLogger(__name__).warning(
                "Sentry init failed: %r", e,
            )

    _INITIALISED = True


def get_logger(name: str) -> Any:
    """Return a structlog logger when available, stdlib logger otherwise.

    Both expose ``.info(msg, **kwargs)`` so callers don't have to branch.
    """
    try:
        import structlog  # type: ignore
        return structlog.get_logger(name)
    except ImportError:
        return logging.getLogger(name)


def bind_job_context(**kv: Any) -> None:
    """Bind kv pairs (job_id, stage) into the structlog contextvars.

    No-op when structlog isn't installed. Safe to call from anywhere in
    the orchestrator — every subsequent log call inherits the context.
    """
    try:
        import structlog  # type: ignore
        structlog.contextvars.bind_contextvars(**kv)
    except ImportError:
        pass


def clear_job_context() -> None:
    try:
        import structlog  # type: ignore
        structlog.contextvars.clear_contextvars()
    except ImportError:
        pass


def capture_exception(exc: BaseException, *, job_id: str | None = None,
                      stage: str | None = None) -> None:
    """Forward to Sentry if available; no-op otherwise.

    The orchestrator's outer try/except still records the error on the
    job; this is purely for shipping the traceback off-box.
    """
    try:
        import sentry_sdk  # type: ignore
        with sentry_sdk.push_scope() as scope:
            if job_id:
                scope.set_tag("job_id", job_id)
            if stage:
                scope.set_tag("stage", stage)
            sentry_sdk.capture_exception(exc)
    except ImportError:
        # Sentry not installed — caller already logged the error locally.
        pass
    except Exception as forward_exc:
        # Sentry forwarder itself blew up; don't let observability mask the
        # original error, but log so we know the dashboard is missing events.
        logging.getLogger(__name__).warning(
            "observability.capture_exception: forwarder failed (%r); "
            "original error was %r", forward_exc, exc,
        )
