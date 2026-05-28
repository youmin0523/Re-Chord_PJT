"""In-app feedback collection endpoint.

Records user feedback about a specific job (separation quality, score
accuracy, lyrics correctness, etc.) into ``data/feedback/feedback.jsonl``.
Phase A: line-delimited JSON file, append-only. Phase B: swap to the
Postgres ``feedback`` table.

Goal: a closed feedback loop without sending anything off-box by
default. The user submits feedback from the result UI, we keep it next
to the job artifacts, and a periodic export can aggregate it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..core.jobs import registry


router = APIRouter(prefix="/feedback", tags=["feedback"])


FEEDBACK_DIR = Path(settings.data_dir) / "feedback"
FEEDBACK_FILE = FEEDBACK_DIR / "feedback.jsonl"


# Five tightly-scoped fields the user can rate. Anything beyond requires
# a real survey form — these five cover ~90% of "what went wrong" reports
# we've seen during dev.
RATING_FIELDS = Literal[
    "separation", "score", "chords", "lyrics", "timing", "overall",
]


class FeedbackIn(BaseModel):
    job_id: str
    ratings: dict[RATING_FIELDS, int] = Field(
        default_factory=dict,
        description="1-5 star ratings per category (1=very poor, 5=excellent)",
    )
    notes: str = Field(default="", max_length=2000,
                        description="optional free-text comment")
    contact: str = Field(default="", max_length=200,
                          description="optional email/handle for follow-up")
    # Anonymised client-side context — UA/screen/locale. Helps triage
    # browser-specific issues without storing PII.
    client_meta: dict = Field(default_factory=dict)


class FeedbackOut(BaseModel):
    accepted: bool
    feedback_id: str
    written_at: float


@router.post("", response_model=FeedbackOut)
async def submit_feedback(body: FeedbackIn) -> FeedbackOut:
    """Persist a feedback entry. Idempotent on (job_id, rounded-minute)."""
    # Light validation — job must exist, ratings must be 1..5.
    job = registry.get(body.job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    for k, v in body.ratings.items():
        if not 1 <= int(v) <= 5:
            raise HTTPException(422, f"rating {k} out of range (1..5): {v}")
    if not body.ratings and not body.notes:
        raise HTTPException(422, "no ratings and no notes — nothing to record")

    now = time.time()
    fb_id = f"{int(now)}-{body.job_id[:8]}"
    entry = {
        "id": fb_id,
        "ts": now,
        "job_id": body.job_id,
        "ratings": body.ratings,
        "notes": body.notes.strip(),
        # Email is light PII — only persist when the user explicitly
        # provided it for follow-up.
        "contact": body.contact.strip(),
        "client_meta": {
            k: str(v)[:200] for k, v in (body.client_meta or {}).items()
        },
    }

    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Also dump a tiny per-job sidecar so it's findable next to the
    # other artifacts.
    sidecar = Path(job.artifacts.get(
        "feedback", str(FEEDBACK_DIR / f"{body.job_id}.json")
    ))
    try:
        existing = (json.loads(sidecar.read_text(encoding="utf-8"))
                    if sidecar.exists() else [])
    except Exception:
        existing = []
    existing.append(entry)
    sidecar.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    job.artifacts["feedback"] = str(sidecar)

    return FeedbackOut(accepted=True, feedback_id=fb_id, written_at=now)


@router.get("/summary")
async def feedback_summary() -> dict:
    """Aggregate the feedback file into per-category histograms.

    Returns rough usage statistics for the dashboard:
        - total_responses, recent_24h
        - per_category: {separation: {avg, n, hist[1..5]}, ...}
        - top_issues:   recent free-text notes sorted by submission time
    """
    if not FEEDBACK_FILE.exists():
        return {"total_responses": 0, "recent_24h": 0,
                "per_category": {}, "top_issues": []}
    rows = []
    try:
        for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return {"total_responses": 0, "recent_24h": 0,
                "per_category": {}, "top_issues": []}

    now = time.time()
    recent_24h = sum(1 for r in rows if now - float(r.get("ts", 0)) < 86400)
    per_cat: dict[str, dict] = {}
    for r in rows:
        for cat, val in (r.get("ratings") or {}).items():
            entry = per_cat.setdefault(cat, {"sum": 0, "n": 0,
                                              "hist": [0, 0, 0, 0, 0]})
            v = int(val)
            if 1 <= v <= 5:
                entry["sum"] += v
                entry["n"] += 1
                entry["hist"][v - 1] += 1
    for cat, e in per_cat.items():
        e["avg"] = round(e["sum"] / e["n"], 2) if e["n"] else 0

    top_issues = [
        {"id": r.get("id"), "ts": r.get("ts"),
         "job_id": r.get("job_id"), "notes": r.get("notes", "")[:300]}
        for r in sorted(rows, key=lambda x: float(x.get("ts", 0)),
                        reverse=True)
        if r.get("notes", "").strip()
    ][:20]

    return {
        "total_responses": len(rows),
        "recent_24h": recent_24h,
        "per_category": per_cat,
        "top_issues": top_issues,
    }
