"""Setlist / project endpoints — server-side persistence for job groupings.

Phase A is single-user / single-device so we keep this in-memory + a JSON
file under ``data/setlists.json`` for restart resilience. Phase B will move
this to PostgreSQL when auth lands.

A Setlist is just an ordered list of job IDs with a display name. The
frontend's localStorage cache mirrors this; server is the source of truth
when present, client cache is the offline fallback.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings


router = APIRouter(prefix="/setlists", tags=["setlists"])
_LOCK = Lock()


def _store_path() -> Path:
    p = settings.data_dir / "setlists.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load() -> list[dict]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return list(raw.get("setlists") or [])
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    p = _store_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "setlists": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)


def _now() -> int:
    return int(time.time())


class Setlist(BaseModel):
    id: str
    name: str
    job_ids: list[str] = Field(default_factory=list)
    created_at: int
    updated_at: int


class SetlistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    job_ids: list[str] = Field(default_factory=list)


class SetlistPatch(BaseModel):
    name: str | None = None
    job_ids: list[str] | None = None


@router.get("")
async def list_setlists() -> list[Setlist]:
    with _LOCK:
        return [Setlist(**s) for s in _load()]


@router.post("", status_code=201)
async def create_setlist(body: SetlistCreate) -> Setlist:
    with _LOCK:
        items = _load()
        sid = f"sl_{uuid.uuid4().hex[:10]}"
        entry = {
            "id": sid,
            "name": body.name.strip() or "이름없는 셋",
            "job_ids": list(dict.fromkeys(body.job_ids)),  # dedupe, preserve order
            "created_at": _now(),
            "updated_at": _now(),
        }
        items.insert(0, entry)
        _save(items)
        return Setlist(**entry)


@router.get("/{setlist_id}")
async def get_setlist(setlist_id: str) -> Setlist:
    with _LOCK:
        items = _load()
        for s in items:
            if s["id"] == setlist_id:
                return Setlist(**s)
    raise HTTPException(status_code=404, detail="setlist not found")


@router.patch("/{setlist_id}")
async def patch_setlist(setlist_id: str, body: SetlistPatch) -> Setlist:
    with _LOCK:
        items = _load()
        for s in items:
            if s["id"] != setlist_id:
                continue
            if body.name is not None and body.name.strip():
                s["name"] = body.name.strip()
            if body.job_ids is not None:
                s["job_ids"] = list(dict.fromkeys(body.job_ids))
            s["updated_at"] = _now()
            _save(items)
            return Setlist(**s)
    raise HTTPException(status_code=404, detail="setlist not found")


@router.delete("/{setlist_id}", status_code=204)
async def delete_setlist(setlist_id: str) -> None:
    with _LOCK:
        items = _load()
        next_items = [s for s in items if s["id"] != setlist_id]
        if len(next_items) == len(items):
            raise HTTPException(status_code=404, detail="setlist not found")
        _save(next_items)


@router.post("/{setlist_id}/jobs/{job_id}")
async def add_job(setlist_id: str, job_id: str) -> Setlist:
    with _LOCK:
        items = _load()
        for s in items:
            if s["id"] != setlist_id:
                continue
            if job_id not in s["job_ids"]:
                s["job_ids"].append(job_id)
                s["updated_at"] = _now()
                _save(items)
            return Setlist(**s)
    raise HTTPException(status_code=404, detail="setlist not found")


@router.delete("/{setlist_id}/jobs/{job_id}")
async def remove_job(setlist_id: str, job_id: str) -> Setlist:
    with _LOCK:
        items = _load()
        for s in items:
            if s["id"] != setlist_id:
                continue
            s["job_ids"] = [j for j in s["job_ids"] if j != job_id]
            s["updated_at"] = _now()
            _save(items)
            return Setlist(**s)
    raise HTTPException(status_code=404, detail="setlist not found")
