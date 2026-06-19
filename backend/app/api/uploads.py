"""File upload endpoint. Multipart, no extension whitelist (ffprobe-validated)."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..config import settings
from ..core.ops import fingerprint_audio, fingerprints_match
from ..core.jobs import registry
from ..core.paths import ensure_dir, new_job_id
from ..pipeline.ingest import ffprobe_streams, pick_audio_stream


router = APIRouter(prefix="/uploads", tags=["uploads"])


class DuplicateCheckResponse(BaseModel):
    fingerprint: str | None
    duration_sec: float
    source: str          # "pyacoustid" | "fpcalc" | "none"
    matches: list[dict]  # existing jobs with the same fingerprint


@router.post("/fingerprint")
async def fingerprint_upload(file: UploadFile = File(...)) -> DuplicateCheckResponse:
    """Hash an upload via chromaprint, return any prior jobs that match.

    Lightweight pre-flight: the user can ask "did I already process this?"
    before kicking off a 2-3 minute conversion. We compute the fingerprint
    on the freshly-uploaded file, compare against fingerprints stored on
    earlier jobs in the in-memory registry (Phase B: query the DB instead),
    and return any duplicates.
    """
    upload_id = new_job_id()
    dest_dir = settings.uploads_dir / f"fp_{upload_id}"
    ensure_dir(dest_dir)
    safe_name = Path(file.filename or "source").name
    dest = dest_dir / safe_name
    with dest.open("wb") as fp:
        shutil.copyfileobj(file.file, fp, length=1024 * 1024)

    try:
        fpr = fingerprint_audio(dest)
    finally:
        # We don't keep the file — only the hash.
        try:
            dest.unlink()
            dest_dir.rmdir()
        except OSError:
            pass

    matches: list[dict] = []
    if fpr.fingerprint:
        for job in registry.list(limit=500):
            other = job.meta.get("fingerprint")
            if other and fingerprints_match(fpr.fingerprint, other):
                matches.append({
                    "job_id": job.id,
                    "title": job.meta.get("source_title"),
                    "duration_sec": job.meta.get("source_duration"),
                    "created_at": job.created_at,
                })
    return DuplicateCheckResponse(
        fingerprint=fpr.fingerprint,
        duration_sec=fpr.duration_sec,
        source=fpr.source,
        matches=matches,
    )


@router.post("")
async def upload_file(file: UploadFile = File(...)) -> dict:
    """Receive a file and stage it under data/uploads/<upload_id>/.

    Returns a path the client passes back as the job input.
    """
    if file.size is not None and file.size > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file too large")

    upload_id = new_job_id()
    dest_dir = settings.uploads_dir / f"upload_{upload_id}"
    ensure_dir(dest_dir)
    safe_name = Path(file.filename or "source").name  # strip any path components
    dest = dest_dir / safe_name

    with dest.open("wb") as fp:
        shutil.copyfileobj(file.file, fp, length=1024 * 1024)

    size = dest.stat().st_size
    if size > settings.max_upload_bytes:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail="file too large")

    try:
        probe = ffprobe_streams(dest)
        audio = pick_audio_stream(probe)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"unsupported media: {e!s}")

    fmt = probe.get("format", {})
    duration = float(fmt.get("duration") or 0.0)
    # Reject too-short clips up front (a 400) rather than letting them blow up
    # 500-deep in the separator (bs_roformer tensor-size mismatch on <~8s audio).
    # duration==0 means ffprobe couldn't read it — let the pipeline guard handle.
    if duration and duration < settings.min_audio_duration_sec:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=(
                f"파일 길이가 너무 짧습니다. 최소 {int(settings.min_audio_duration_sec)}초 "
                f"이상이어야 합니다 (현재 {duration:.1f}초)."
            ),
        )
    return {
        "upload_id": upload_id,
        "path": str(dest),
        "filename": dest.name,
        "size_bytes": size,
        "container": fmt.get("format_name", "?"),
        "audio_codec": audio.get("codec_name", "unknown"),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "duration_sec": duration,
    }
