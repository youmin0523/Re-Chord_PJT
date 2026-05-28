"""Operational helpers — fingerprint, disk-check, version probe, cleanup.

All sync utilities used by the API + orchestrator. Keep `core/` free of
HTTP dependencies so unit tests can import without spinning a FastAPI app.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


# ── Chromaprint duplicate-detection ────────────────────────────────────────

@dataclass
class FingerprintResult:
    fingerprint: str | None
    duration_sec: float
    source: str        # "pyacoustid" | "fpcalc" | "none"
    error: str | None = None


def fingerprint_audio(audio_path: Path) -> FingerprintResult:
    """Compute a chromaprint fingerprint for one audio file.

    Tries (1) pyacoustid (pure-Python wrapper around fpcalc) first, then
    (2) the ``fpcalc`` CLI from ffmpeg's chromaprint, then gives up. The
    fingerprint is the standard 32-bit-int hash string fpcalc returns;
    duplicate detection compares fingerprints character-by-character or
    uses ``chromaprint.compare`` distance.
    """
    # Path 1: pyacoustid (Python).
    try:
        import acoustid  # type: ignore
        duration, fp = acoustid.fingerprint_file(str(audio_path))
        return FingerprintResult(
            fingerprint=fp.decode() if isinstance(fp, bytes) else str(fp),
            duration_sec=float(duration),
            source="pyacoustid",
        )
    except Exception:
        pass

    # Path 2: fpcalc CLI.
    fpcalc = shutil.which("fpcalc")
    if fpcalc:
        try:
            proc = subprocess.run(
                [fpcalc, "-json", "-length", "120", str(audio_path)],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                import json as _json
                data = _json.loads(proc.stdout or "{}")
                return FingerprintResult(
                    fingerprint=str(data.get("fingerprint") or ""),
                    duration_sec=float(data.get("duration") or 0.0),
                    source="fpcalc",
                )
        except Exception as e:
            return FingerprintResult(
                fingerprint=None, duration_sec=0.0,
                source="fpcalc", error=repr(e),
            )

    return FingerprintResult(
        fingerprint=None, duration_sec=0.0,
        source="none",
        error="chromaprint backend not available (install pyacoustid or fpcalc)",
    )


def fingerprints_match(a: str, b: str, max_distance: float = 0.05) -> bool:
    """Cheap fingerprint equality. We don't compute true Hamming distance
    on the raw bitstream — we compare the substring tokens. Good enough
    for "exact same file" duplicate detection at upload time."""
    if not a or not b:
        return False
    if a == b:
        return True
    # Take a 1024-char prefix; if the first 90% match, treat as duplicate.
    cut = min(len(a), len(b), 1024)
    diff = sum(1 for i in range(cut) if a[i] != b[i])
    return (diff / max(1, cut)) <= max_distance


# ── Disk pre-flight ────────────────────────────────────────────────────────

@dataclass
class DiskCheck:
    free_gb: float
    required_gb: float
    ok: bool
    advice: str


# Per-mode disk budget (rough): includes work_dir + stems_dir + output_dir
# per-job artifacts. Stems mode is largest because it keeps 6 stems.
_MODE_DISK_GB: dict[str, float] = {
    "quick_mr": 1.0,
    "karaoke":  2.5,
    "stems":    6.0,
    "pro":      8.0,
}


def disk_preflight(target_dir: Path, mode: str = "karaoke") -> DiskCheck:
    """Check there's enough free space on the drive holding ``target_dir``."""
    try:
        usage = shutil.disk_usage(str(target_dir))
        free_gb = usage.free / (1024 ** 3)
    except Exception:
        return DiskCheck(0.0, 0.0, True, "could not measure disk; skipping check")

    required_gb = _MODE_DISK_GB.get(mode, 4.0)
    ok = free_gb >= required_gb
    if ok:
        advice = "OK"
    else:
        advice = (
            f"디스크 여유 공간 부족: {free_gb:.1f} GB / 필요 ~{required_gb:.1f} GB. "
            f"오래된 작업 정리 후 재시도하세요."
        )
    return DiskCheck(free_gb, required_gb, ok, advice)


# ── Auto-cleanup ───────────────────────────────────────────────────────────

@dataclass
class CleanupResult:
    files_removed: int
    bytes_freed: int
    paths: list[str]


def cleanup_old_artifacts(
    roots: list[Path],
    max_age_hours: float = 72.0,
    dry_run: bool = False,
) -> CleanupResult:
    """Delete files older than ``max_age_hours`` under each root path.

    Used by an admin endpoint + a daily background task. Default 72h
    (3 days) is conservative — users with active work shouldn't lose
    artifacts mid-session. Pass ``dry_run=True`` to enumerate without
    deleting (useful for the UI "이만큼 정리 가능합니다" preview).
    """
    cutoff = time.time() - max_age_hours * 3600
    files_removed = 0
    bytes_freed = 0
    removed_paths: list[str] = []

    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                mtime = p.stat().st_mtime
                size = p.stat().st_size
            except OSError:
                continue
            if mtime < cutoff:
                if not dry_run:
                    try:
                        p.unlink()
                    except OSError:
                        continue
                files_removed += 1
                bytes_freed += size
                if len(removed_paths) < 200:
                    removed_paths.append(str(p))

        # Remove now-empty subdirectories (best-effort, leaf-first).
        if not dry_run:
            for d in sorted(root.rglob("*"), key=lambda x: -len(str(x))):
                if d.is_dir():
                    try:
                        d.rmdir()
                    except OSError:
                        pass

    return CleanupResult(files_removed, bytes_freed, removed_paths)


# ── Version probes ─────────────────────────────────────────────────────────

@dataclass
class ToolVersion:
    name: str
    version: str | None
    available: bool
    path: str | None = None


def _probe(cmd: list[str], pattern: str) -> tuple[str | None, str | None]:
    """Run ``cmd`` and extract a version string with ``pattern`` (regex)."""
    exe = shutil.which(cmd[0])
    if not exe:
        # Also try project-local bin/.
        proj_root = Path(__file__).resolve().parents[3]
        for candidate in (
            proj_root / "bin" / f"{cmd[0]}.exe",
            proj_root / "bin" / cmd[0],
        ):
            if candidate.exists():
                exe = str(candidate)
                break
    if not exe:
        return (None, None)
    try:
        proc = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=5)
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        m = re.search(pattern, text)
        return ((m.group(1) if m else None), exe)
    except Exception:
        return (None, exe)


def probe_tool_versions() -> list[ToolVersion]:
    """Self-report version of every external tool we depend on."""
    items: list[ToolVersion] = []
    for name, cmd, pattern in [
        ("ffmpeg",      ["ffmpeg", "-version"],          r"ffmpeg version (\S+)"),
        ("ffprobe",     ["ffprobe", "-version"],         r"ffprobe version (\S+)"),
        ("yt-dlp",      ["yt-dlp", "--version"],         r"(\d+\.\d+\.\d+\S*)"),
        ("rubberband",  ["rubberband", "--help"],        r"Rubber Band\D+(\d+\.\d+\.\d+)"),
        ("fluidsynth",  ["fluidsynth", "--version"],     r"FluidSynth runtime version (\d+\.\d+\.\d+)"),
        ("fpcalc",      ["fpcalc", "-version"],          r"fpcalc version (\S+)"),
    ]:
        version, exe = _probe(cmd, pattern)
        items.append(ToolVersion(
            name=name, version=version,
            available=(exe is not None),
            path=exe,
        ))
    return items
