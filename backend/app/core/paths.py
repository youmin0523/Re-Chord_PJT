"""Filesystem path helpers for Windows long paths and atomic moves."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


def long_path(p: str | os.PathLike[str]) -> str:
    """Return a Windows long-path safe string for paths that may exceed 260 chars.

    On non-Windows, returns the path unchanged.
    """
    s = os.fspath(p)
    if sys.platform != "win32":
        return s
    if s.startswith("\\\\?\\") or s.startswith("\\\\.\\"):
        return s
    abs_p = os.path.abspath(s)
    if abs_p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abs_p.lstrip("\\")
    return "\\\\?\\" + abs_p


def ensure_dir(p: str | os.PathLike[str]) -> Path:
    path = Path(p)
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write bytes to a temp file in the same directory, then atomically rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
