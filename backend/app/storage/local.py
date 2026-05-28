"""Local filesystem storage — Phase A default.

Keys are flat paths under a configurable root (``settings.data_dir / "storage"``
by default). URLs are returned as ``file://`` so consumers can detect
"served from local" via the scheme; the actual web exposure happens via
the existing ``/jobs/{id}/download/{kind}`` route in the API layer.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class LocalStorage:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "LocalStorage":
        root_str = os.environ.get("STORAGE_LOCAL_ROOT")
        if root_str:
            return cls(Path(root_str))
        # Fall back to project data dir.
        from ..config import settings
        return cls(settings.data_dir / "storage")

    def _path(self, key: str) -> Path:
        # Disallow absolute paths or directory traversal.
        if key.startswith(("/", "\\")) or ".." in Path(key).parts:
            raise ValueError(f"unsafe key: {key!r}")
        return self.root / key

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p.as_uri()

    def put_file(self, key: str, src_path, content_type: str | None = None) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_path, p)
        return p.as_uri()

    def get_url(self, key: str, *, signed: bool = False, ttl_sec: int = 3600) -> str:
        # No notion of signed URLs locally; we just return the file URI.
        return self._path(key).as_uri()

    def delete(self, key: str) -> bool:
        try:
            self._path(key).unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def exists(self, key: str) -> bool:
        return self._path(key).exists()
