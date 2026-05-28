"""File / URL attachment helpers for the chat endpoint.

Lightweight analysis only — we don't run the full MR pipeline (stem
separation etc.) for an inline chat attachment. Just enough to surface
key + BPM + duration so the assistant can answer "what tempo is this?".

Re-uses ``backend.app.pipeline.ingest.ingest_url`` for YouTube/Spotify
links and ``pipeline.analyze.analyze`` for key/BPM. Both already work
with arbitrary local paths, so the chat layer stays thin.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from ..config import settings
from ..core.paths import ensure_dir
from ..pipeline.ingest import ingest_url, is_url


def _chat_attach_dir(session_id: str, attachment_id: str) -> Path:
    path = settings.uploads_dir / "chat" / session_id / attachment_id
    ensure_dir(path)
    return path


async def stage_uploaded_file(
    session_id: str,
    attachment_id: str,
    upload: UploadFile,
) -> Path:
    """Persist a multipart upload to ``data/uploads/chat/{sid}/{aid}/``.

    Returns the absolute path. We stream the body in 1 MB chunks so a big
    file doesn't materialize in memory.
    """
    dest_dir = _chat_attach_dir(session_id, attachment_id)
    safe_name = Path(upload.filename or "attachment").name
    dest = dest_dir / safe_name
    # shutil.copyfileobj is synchronous — run on the thread pool.
    def _copy() -> None:
        with dest.open("wb") as fp:
            shutil.copyfileobj(upload.file, fp, length=1024 * 1024)
    await asyncio.to_thread(_copy)
    return dest


async def ingest_url_for_chat(
    session_id: str,
    attachment_id: str,
    url: str,
) -> tuple[Path, str]:
    """Download a remote URL via yt-dlp into the chat attachment dir.

    Returns ``(local_path, title)``. Raises if the URL isn't recognized
    or yt-dlp fails.
    """
    if not is_url(url):
        raise ValueError(f"not a URL: {url!r}")
    dest_dir = _chat_attach_dir(session_id, attachment_id)
    # ingest_url is synchronous (subprocess-based) — push to thread pool.
    result = await asyncio.to_thread(
        ingest_url, url, f"chat_{session_id}_{attachment_id}", dest_dir,
    )
    return result.source, result.title or ""


async def quick_analyze(path: Path) -> dict[str, Any]:
    """Run a lightweight key/BPM analysis. Returns a serializable dict
    (or ``{}`` on failure — the chat surface should degrade gracefully).
    """
    def _run() -> dict[str, Any]:
        try:
            from ..pipeline.analyze import analyze  # lazy: librosa is heavy
            r = analyze(str(path))
            d = asdict(r)
            # Round floats so the JSON stays compact and the prompt block
            # doesn't drown in noise digits.
            for k in ("key_confidence", "bpm_confidence"):
                if k in d and isinstance(d[k], float):
                    d[k] = round(d[k], 3)
            if "bpm" in d and isinstance(d["bpm"], float):
                d["bpm"] = round(d["bpm"], 1)
            if "duration_sec" in d and isinstance(d["duration_sec"], float):
                d["duration_sec"] = round(d["duration_sec"], 2)
            return d
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    return await asyncio.to_thread(_run)


def render_attachment_block(
    attachments: list[dict[str, Any]],
    *,
    locale: str = "ko",
) -> str:
    """Render the attachment summaries as a system-prompt block so the
    LLM knows what the user just attached without re-asking.
    """
    if not attachments:
        return ""
    if locale == "en":
        header = (
            "Attachments analyzed this turn — quote these numbers verbatim "
            "when the user asks about key/BPM/duration:"
        )
    else:
        header = (
            "이번 턴에 분석된 첨부 — 사용자가 키/BPM/길이를 물으면 아래 값을 "
            "그대로 인용하세요:"
        )
    lines = [header, ""]
    for a in attachments:
        kind = a.get("kind") or "?"
        name = a.get("filename") or a.get("url") or a.get("path") or "?"
        lines.append(f"- {kind}: {name}")
        qa = a.get("quick_analysis") or {}
        if "error" in qa:
            lines.append(f"  · 분석 실패: {qa['error']}")
            continue
        if qa.get("key_name"):
            lines.append(f"  · 키: {qa['key_name']} (신뢰도 {qa.get('key_confidence', 0):.2f})")
        if qa.get("bpm"):
            lines.append(f"  · BPM: {qa['bpm']:.1f} (신뢰도 {qa.get('bpm_confidence', 0):.2f})")
        if qa.get("duration_sec"):
            secs = qa["duration_sec"]
            m, s = divmod(int(secs), 60)
            lines.append(f"  · 길이: {m}:{s:02d} ({secs:.1f}s)")
    return "\n".join(lines).strip()


__all__ = [
    "stage_uploaded_file",
    "ingest_url_for_chat",
    "quick_analyze",
    "render_attachment_block",
]
