"""Per-job rehearsal notes — annotations the band-master adds for a song.

Use cases:
  - "이번 주는 브릿지 스킵"
  - "후렴 들어가기 전 1마디 쉼"
  - "Bb 색소폰은 8마디부터 콜라보"

Stored as a JSON file under ``data/output/{job_id}/notes.json`` so it
lives with the rest of the artifacts and survives server restarts. A
``Note`` is timeline-aware (optional start_sec / end_sec) so the
performance view can render markers on the playhead. Plain prose notes
(no start time) attach to the top of the cue sheet.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..core.jobs import registry
from ..core.paths import ensure_dir


router = APIRouter(prefix="/jobs", tags=["notes"])


def _notes_path(job_id: str) -> Path:
    return settings.output_dir / job_id / "notes.json"


class Note(BaseModel):
    id: str
    text: str
    start_sec: float | None = None
    end_sec: float | None = None
    kind: str = "note"           # "note" | "skip" | "cue" | "warning"
    created_at: int
    updated_at: int


class NoteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, ge=0.0)
    kind: str = Field(default="note")


def _load(job_id: str) -> list[dict]:
    p = _notes_path(job_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return list(raw.get("notes") or [])
    except Exception:
        return []


def _save(job_id: str, notes: list[dict]) -> Path:
    p = _notes_path(job_id)
    ensure_dir(p.parent)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "notes": notes}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)
    return p


def _now() -> int:
    return int(time.time())


def _check_job(job_id: str) -> None:
    if registry.get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")


@router.get("/{job_id}/notes")
async def list_notes(job_id: str) -> dict:
    _check_job(job_id)
    return {"job_id": job_id, "notes": _load(job_id)}


@router.post("/{job_id}/notes", status_code=201)
async def create_note(job_id: str, body: NoteIn) -> Note:
    _check_job(job_id)
    notes = _load(job_id)
    note = {
        "id": f"n_{uuid.uuid4().hex[:10]}",
        "text": body.text.strip(),
        "start_sec": body.start_sec,
        "end_sec": body.end_sec,
        "kind": body.kind,
        "created_at": _now(),
        "updated_at": _now(),
    }
    notes.append(note)
    _save(job_id, notes)
    job = registry.get(job_id)
    if job is not None:
        job.artifacts["notes_json"] = str(_notes_path(job_id))
    return Note(**note)


@router.patch("/{job_id}/notes/{note_id}")
async def patch_note(job_id: str, note_id: str, body: NoteIn) -> Note:
    _check_job(job_id)
    notes = _load(job_id)
    for n in notes:
        if n["id"] != note_id:
            continue
        n["text"] = body.text.strip()
        n["start_sec"] = body.start_sec
        n["end_sec"] = body.end_sec
        n["kind"] = body.kind
        n["updated_at"] = _now()
        _save(job_id, notes)
        return Note(**n)
    raise HTTPException(status_code=404, detail="note not found")


@router.delete("/{job_id}/notes/{note_id}", status_code=204)
async def delete_note(job_id: str, note_id: str) -> None:
    _check_job(job_id)
    notes = _load(job_id)
    next_notes = [n for n in notes if n["id"] != note_id]
    if len(next_notes) == len(notes):
        raise HTTPException(status_code=404, detail="note not found")
    _save(job_id, next_notes)
