"""Storage interface + backend factory.

``get_storage()`` picks the concrete backend based on ``STORAGE_BACKEND``
env var (default: local). Backends are lazy-imported so missing boto3 /
asyncio_minio doesn't break the local path.
"""

from __future__ import annotations

import os
from typing import Protocol


class Storage(Protocol):
    """The minimum contract every storage backend must satisfy."""

    name: str                           # "local" | "r2" | "s3"

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """Persist ``data`` at ``key``. Return the resolved storage URL."""
        ...

    def put_file(self, key: str, src_path, content_type: str | None = None) -> str:
        """Persist a file at ``src_path``. Cheaper than reading into memory."""
        ...

    def get_url(self, key: str, *, signed: bool = False, ttl_sec: int = 3600) -> str:
        """Return a URL the client can fetch from. ``signed`` for time-limited."""
        ...

    def delete(self, key: str) -> bool:
        ...

    def exists(self, key: str) -> bool:
        ...


_singleton: Storage | None = None


def get_storage() -> Storage:
    """Return the configured storage backend. Memoised."""
    global _singleton
    if _singleton is not None:
        return _singleton
    backend = (os.environ.get("STORAGE_BACKEND") or "local").strip().lower()
    if backend in ("r2", "cloudflare"):
        from .s3 import S3CompatibleStorage
        _singleton = S3CompatibleStorage.from_env(default_endpoint_kind="r2")
    elif backend in ("s3", "aws"):
        from .s3 import S3CompatibleStorage
        _singleton = S3CompatibleStorage.from_env(default_endpoint_kind="aws")
    else:
        from .local import LocalStorage
        _singleton = LocalStorage.from_env()
    return _singleton
