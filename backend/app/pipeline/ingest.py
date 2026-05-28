"""Input ingestion: detect URL vs file, route to yt-dlp or local validation.

No extension whitelist — anything ffprobe can decode is accepted.
yt-dlp handles 1800+ sites via its extractor registry.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..config import settings
from ..core.paths import ensure_dir


URL_RE = re.compile(r"^https?://", re.IGNORECASE)


@dataclass
class IngestResult:
    job_id: str
    source: Path
    kind: Literal["url", "file"]
    origin: str
    audio_codec: str
    sample_rate: int
    channels: int
    bit_rate: int | None
    duration_sec: float
    container: str
    title: str = ""              # human-readable name (yt-dlp title or file stem)


def is_url(s: str) -> bool:
    return bool(URL_RE.match(s.strip()))


def validate_url_safety(url: str) -> None:
    """SSRF guard — reject URLs that resolve to private / loopback /
    link-local addresses so a malicious input can't make the server
    fetch internal services (cloud metadata endpoints, localhost admin
    panels, etc.).

    Raises ValueError on a blocked URL. Public hostnames pass. DNS
    resolution failures are *not* fatal here — yt-dlp will surface a
    clean error downstream — but a host that resolves to a private
    range is blocked outright.

    Override for trusted internal deployments via
    RECHORD_ALLOW_PRIVATE_URLS=1 (e.g. an on-prem media server).
    """
    import os
    if os.environ.get("RECHORD_ALLOW_PRIVATE_URLS", "").strip() == "1":
        return

    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").strip()
    if not host:
        raise ValueError("URL has no host")

    # Block obvious metadata / localhost aliases by name.
    lowered = host.lower()
    _BLOCKED_NAMES = {
        "localhost", "metadata.google.internal", "metadata",
    }
    if lowered in _BLOCKED_NAMES or lowered.endswith(".localhost"):
        raise ValueError(f"blocked host: {host}")

    # Resolve all A/AAAA records; if ANY resolves into a private/reserved
    # range, reject (defends against DNS-rebinding to a single bad IP).
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        # Can't resolve — let yt-dlp produce its own error rather than
        # blocking a transient DNS hiccup.
        return
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(
                f"blocked URL — host {host} resolves to a non-public "
                f"address ({addr})"
            )


def ffprobe_streams(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe not found on PATH")
    proc = subprocess.run(
        [exe, "-v", "error", "-show_format", "-show_streams",
         "-print_format", "json", str(path)],
        capture_output=True, text=True, check=False, encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def pick_audio_stream(probe: dict) -> dict:
    for s in probe.get("streams", []):
        if s.get("codec_type") == "audio":
            return s
    raise ValueError("no audio stream found in source")


MIN_DURATION_SEC = 1.0
MAX_DURATION_SEC = 60 * 30   # 30 minutes — anything longer is likely user error.


def _validate_audio_props(audio: dict, fmt: dict, source_label: str) -> None:
    """Sanity-check probed metadata. Raises ValueError on hard rejects."""
    sr = int(audio.get("sample_rate") or 0)
    channels = int(audio.get("channels") or 0)
    duration = float(fmt.get("duration") or 0.0)
    if sr < 8000:
        raise ValueError(
            f"{source_label}: sample rate too low ({sr} Hz). Need ≥ 8000 Hz."
        )
    if channels < 1:
        raise ValueError(f"{source_label}: no audio channels detected.")
    if duration < MIN_DURATION_SEC:
        raise ValueError(
            f"{source_label}: audio too short ({duration:.2f}s). Need ≥ {MIN_DURATION_SEC}s."
        )
    if duration > MAX_DURATION_SEC:
        raise ValueError(
            f"{source_label}: audio too long ({duration:.1f}s, "
            f"max {MAX_DURATION_SEC}s)."
        )


def ingest_url(url: str, job_id: str, dest_dir: Path) -> IngestResult:
    """Download via yt-dlp keeping the original audio codec."""
    # SSRF guard before we hand the URL to yt-dlp.
    validate_url_safety(url)
    # Invoke as ``python -m yt_dlp`` so we don't depend on the uvicorn worker
    # inheriting the venv's Scripts/ on PATH (shutil.which("yt-dlp") returns
    # None when uvicorn is launched via .venv\Scripts\uvicorn.exe directly).
    ensure_dir(dest_dir)
    out_template = str(dest_dir / "source.%(ext)s")
    # Two sentinel prints — one for the final on-disk path, one for the title.
    # The order is deterministic (yt-dlp emits them in cmdline order).
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio/best",
        "--no-playlist",
        "--no-progress",
        "-o", out_template,
        # ``--print`` implies ``--simulate`` unless WHEN is post_process or
        # after_move — without the prefix yt-dlp skips the actual download
        # and only prints the template. ``after_move`` runs after the file
        # has been finalised on disk, so filepath is populated.
        "--print", "after_move:PATH::%(filepath,_filename)s",
        "--print", "after_move:TITLE::%(title)s",
        url,
    ]
    if settings.ytdlp_cookies_from_browser:
        cmd.extend(["--cookies-from-browser", settings.ytdlp_cookies_from_browser])

    # Hard timeout so a slow/stalled remote can't hang the worker forever.
    # Configurable via RECHORD_YTDLP_TIMEOUT_SEC (default 600s = 10 min,
    # generous for a long worship set on a slow connection).
    import os as _os
    try:
        _dl_timeout = float(_os.environ.get("RECHORD_YTDLP_TIMEOUT_SEC", "600"))
    except ValueError:
        _dl_timeout = 600.0
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_dl_timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"yt-dlp download timed out after {_dl_timeout:.0f}s — the source "
            f"may be very large or the connection is slow. Try a direct file "
            f"upload, or raise RECHORD_YTDLP_TIMEOUT_SEC."
        ) from None
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if proc.returncode != 0:
        raise RuntimeError(
            f"yt-dlp exit {proc.returncode}: {stderr.strip() or stdout.strip() or '(no output)'}"
        )

    out_lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    candidate: Path | None = None
    title = ""
    for ln in out_lines:
        if ln.startswith("PATH::"):
            p = Path(ln[len("PATH::"):])
            if p.exists():
                candidate = p
        elif ln.startswith("TITLE::"):
            title = ln[len("TITLE::"):]
    if not candidate:
        matches = sorted(dest_dir.glob("source.*"))
        if not matches:
            # Surface yt-dlp's own diagnostic output so users can tell whether
            # this was a JS-runtime miss, a geo-block, sign-in wall, etc.
            diag = (stderr.strip() or stdout.strip() or "(yt-dlp produced no output)")
            raise RuntimeError(f"yt-dlp produced no file. yt-dlp said:\n{diag[-1500:]}")
        candidate = matches[0]

    probe = ffprobe_streams(candidate)
    audio = pick_audio_stream(probe)
    fmt = probe.get("format", {})
    _validate_audio_props(audio, fmt, f"URL {url}")

    # If yt-dlp didn't give us a title, fall back to the metadata tag, then
    # to the bare filename stem.
    if not title:
        tags = (fmt.get("tags") or {})
        title = tags.get("title") or tags.get("TITLE") or candidate.stem

    return IngestResult(
        job_id=job_id,
        source=candidate,
        kind="url",
        origin=url,
        audio_codec=audio.get("codec_name", "unknown"),
        sample_rate=int(audio.get("sample_rate") or 0),
        channels=int(audio.get("channels") or 0),
        bit_rate=int(fmt.get("bit_rate")) if fmt.get("bit_rate") else None,
        duration_sec=float(fmt.get("duration") or 0.0),
        container=fmt.get("format_name", "?"),
        title=title,
    )


def ingest_file(src: Path, job_id: str, dest_dir: Path) -> IngestResult:
    """Validate via ffprobe and copy into the job's uploads directory."""
    if not src.exists():
        raise FileNotFoundError(src)
    size = src.stat().st_size
    if size > settings.max_upload_bytes:
        raise ValueError(
            f"file too large: {size} bytes (limit {settings.max_upload_bytes})"
        )

    ensure_dir(dest_dir)
    dest = dest_dir / f"source{src.suffix}"
    if dest.resolve() != src.resolve():
        shutil.copyfile(src, dest)

    probe = ffprobe_streams(dest)
    audio = pick_audio_stream(probe)
    fmt = probe.get("format", {})
    _validate_audio_props(audio, fmt, f"file {src.name}")
    tags = (fmt.get("tags") or {})
    title = tags.get("title") or tags.get("TITLE") or src.stem

    return IngestResult(
        job_id=job_id,
        source=dest,
        kind="file",
        origin=str(src),
        audio_codec=audio.get("codec_name", "unknown"),
        sample_rate=int(audio.get("sample_rate") or 0),
        channels=int(audio.get("channels") or 0),
        bit_rate=int(fmt.get("bit_rate")) if fmt.get("bit_rate") else None,
        duration_sec=float(fmt.get("duration") or 0.0),
        container=fmt.get("format_name", "?"),
        title=title,
    )


def ingest(input_str: str, job_id: str) -> IngestResult:
    dest = settings.uploads_dir / job_id
    if is_url(input_str):
        return ingest_url(input_str, job_id, dest)
    return ingest_file(Path(input_str), job_id, dest)
