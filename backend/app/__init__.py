"""Re:Chord backend application package.

Pushes a SAFE subset of ``.env`` into ``os.environ`` at the first import of
the package, so modules that read ``os.environ`` DIRECTLY see values placed
in ``.env``:

  * observability — SENTRY_DSN / SENTRY_TRACES_SAMPLE_RATE
  * core.ratelimit — RATELIMIT_*
  * main / queue / pipeline — RECHORD_* (ops token, prewarm, timeouts, …)
  * storage — STORAGE_* / R2_* / AWS_* (R2/S3 offload)

pydantic-settings only populates the Settings object, never os.environ, so
without this those vars are silently ignored.

Crucially this is an ALLOWLIST, not a blanket load: keys like DATABASE_URL,
AUTH_PROVIDER and SUPABASE_* are intentionally "activated by a real env var
only" so the deploy stays in Phase A (guest, no DB) even though their values
live in .env. Loading those would silently flip the app into Phase B and
break guest mode. ``override=False`` semantics: a real shell/service env var
already present always wins.
"""

from pathlib import Path
import os

_ALLOW_PREFIXES = ("RECHORD_", "RATELIMIT_", "SENTRY_", "STORAGE_", "R2_", "AWS_")

try:
    from dotenv import dotenv_values

    _env_path = Path(__file__).resolve().parents[2] / ".env"
    if _env_path.exists():
        for _k, _v in dotenv_values(_env_path).items():
            if _v is None or _k in os.environ:
                continue
            if _k.startswith(_ALLOW_PREFIXES):
                os.environ[_k] = _v
except Exception:  # pragma: no cover - python-dotenv ships with pydantic-settings
    pass
