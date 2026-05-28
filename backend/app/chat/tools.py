"""Tool-calling catalog for the chat assistant (M6).

Two categories:
  - **read tools** run immediately when the LLM invokes them; the result
    is fed back into the next turn as an extra system message.
  - **write tools** require an explicit user confirmation tap in the UI.
    The model surfaces them as a ``tool_confirm`` SSE event; the actual
    HTTP call only happens after the user clicks "Execute" in the
    confirm card (routes through ``POST /chat/sessions/{id}/tools/{name}/execute``).

Tool descriptors here double as both:
  1. OpenAI function-calling schema (``openai_schema`` field), and
  2. Server-side dispatch metadata (``handler`` callable).

The OpenAI streaming integration that wires this catalog into the
``stream_turn`` flow lives outside this module; this file stays pure
data + thin dispatch so it can be unit-tested without spinning up the
whole chat endpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from fastapi import HTTPException


ToolMode = Literal["read", "write"]


@dataclass
class ToolDescriptor:
    name: str
    mode: ToolMode                       # "read" | "write"
    description: str                     # human-facing description (shown in confirm card)
    parameters: dict[str, Any]           # JSON Schema for the function arguments
    handler: Callable[..., Awaitable[dict[str, Any]]] | None = None
    confirm_label_template: str = ""     # i18n-friendly template, e.g. "{job}의 키를 {key}로 변경"
    tags: list[str] = field(default_factory=list)

    def openai_schema(self) -> dict[str, Any]:
        """Shape the OpenAI Chat Completions ``tools[]`` array expects."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# -- handlers ---------------------------------------------------------------
#
# Read-tool handlers must be async and return JSON-serializable dicts. They
# run in the chat session context — for now we don't pass session info, but
# the dispatcher signature allows it.

async def _read_get_job_meta(*, job_id: str, **_kw) -> dict[str, Any]:
    from ..core.jobs import registry  # local import to avoid heavy startup
    job = registry.get(job_id)
    if job is None:
        return {"ok": False, "error": "job_not_found", "job_id": job_id}
    meta = dict(job.meta or {})
    return {
        "ok": True,
        "job_id": job_id,
        "status": job.status,
        "progress": job.progress,
        "title": meta.get("source_title"),
        "key_name": meta.get("key_name"),
        "bpm": meta.get("bpm"),
        "chord_count": meta.get("chord_count"),
        "duration_sec": meta.get("source_duration"),
    }


async def _read_list_recent_jobs(*, limit: int = 10, **_kw) -> dict[str, Any]:
    from ..core.jobs import registry
    limit = max(1, min(int(limit or 10), 50))
    jobs = registry.list(limit=limit)
    return {
        "ok": True,
        "jobs": [
            {
                "id": j.id,
                "title": (j.meta or {}).get("source_title"),
                "status": j.status,
                "key_name": (j.meta or {}).get("key_name"),
                "bpm": (j.meta or {}).get("bpm"),
            }
            for j in jobs
        ],
    }


async def _read_search_music_db(*, query: str, top_k: int = 5, **_kw) -> dict[str, Any]:
    from .music_db import get_db
    hits = get_db().search(query, top_k=int(top_k or 5), min_score=0.3)
    return {
        "ok": True,
        "hits": [
            {
                "kind": h.kind,
                "score": round(h.score, 3),
                "id": h.record.id,
                "title": getattr(h.record, "primary_title", None) or getattr(h.record, "title_ko", None),
                "matched_via": h.matched_via,
            }
            for h in hits
        ],
    }


async def _read_list_setlists(**_kw) -> dict[str, Any]:
    # Setlists endpoint already in api/setlists.py uses an internal store.
    # Direct file load keeps this handler decoupled from the router.
    from ..api import setlists as setlists_api
    items = setlists_api._load()  # type: ignore[attr-defined]
    return {
        "ok": True,
        "setlists": [
            {"id": s["id"], "name": s["name"], "job_count": len(s.get("job_ids") or [])}
            for s in items
        ],
    }


async def _read_analyze_audio_url(*, url: str, **_kw) -> dict[str, Any]:
    """Download + analyze a URL for key/BPM/meter only — no separation,
    no transcription. Returns within ~45 s so the chatbot can answer in
    a single turn without making the user wait for a full conversion job.

    Internally:
      ingest_url -> madmom CNN key + RNN tempo + DBN downbeat.
    Falls back to librosa if any madmom stage misbehaves (see
    ``analyze.py`` / ``sections.py``).
    """
    import asyncio
    import uuid
    from ..pipeline.ingest import ingest
    from ..pipeline.analyze import analyze
    from ..pipeline.sections import detect_beat_grid

    if not url or not url.strip().lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "url must be http(s)"}

    job_id = "quick_" + uuid.uuid4().hex[:8]

    def _do() -> dict[str, Any]:
        ing = ingest(url.strip(), job_id)
        ana = analyze(ing.source)
        bg = detect_beat_grid(ing.source, "auto")
        return {
            "ok": True,
            "job_id": job_id,
            "title": ing.title,
            "source": str(ing.source),
            "duration_sec": ing.duration_sec,
            "key_name": ana.key_name,
            "key_root": ana.key_root,
            "key_mode": ana.key_mode,
            "key_confidence": ana.key_confidence,
            "bpm": ana.bpm,
            "bpm_confidence": ana.bpm_confidence,
            "meter": bg.meter,
            "time_signature": bg.time_signature,
            "is_compound": bg.is_compound,
            "downbeat_count": len(bg.downbeats_sec),
        }

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _do)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def _read_fetch_youtube_lyrics(*, query: str, top_n: int = 3,
                                     fetch_subtitles: bool = True,
                                     **_kw) -> dict[str, Any]:
    """Resolve a worship-song lyrics query against YouTube.

    Use this whenever the user asks for Korean translated lyrics that the
    seed DB doesn't carry verified ``lyrics_lines`` for. Worship teams
    publish lyrics in the video description or as CC; both are authored
    by the team itself so they're far more reliable than generic
    web-search snippets.
    """
    import asyncio
    from .youtube_lyrics import fetch_youtube_lyrics
    # yt-dlp is sync + IO heavy → run in default executor so the event
    # loop isn't blocked during a streaming chat response.
    loop = asyncio.get_running_loop()
    hits = await loop.run_in_executor(
        None,
        lambda: fetch_youtube_lyrics(
            query, top_n=int(top_n or 3), fetch_subtitles=bool(fetch_subtitles),
        ),
    )
    return {
        "ok": True,
        "hits": [
            {
                "video_id": h.video_id,
                "title": h.title,
                "channel": h.channel,
                "url": h.url,
                "confidence": h.confidence,
                "source_tag": h.source_tag,
                "description_lyrics": h.description_lyrics,
                "subtitle_lyrics": h.subtitle_lyrics,
            }
            for h in hits
        ],
    }


async def _read_web_search(*, query: str, n: int = 3, **_kw) -> dict[str, Any]:
    from .web_search import get_search_adapter
    hits = await get_search_adapter().search(query, n=int(n or 3))
    return {
        "ok": True,
        "results": [
            {"title": h.title, "url": h.url, "snippet": h.snippet[:300]}
            for h in hits
        ],
    }


# -- write handlers ---------------------------------------------------------
#
# Write handlers actually mutate state. They run only when the user clicks
# "Execute" on a confirm card, NOT when the LLM emits a tool_call. The
# dispatcher checks ``mode == "write"`` and raises before reaching here.

async def _write_create_job(*, input: str, options: dict | None = None, **_kw) -> dict[str, Any]:
    from ..core.jobs import JobOptions, registry
    from ..core.queue import get_queue
    opts = JobOptions(**(options or {}))
    job = registry.create(input_str=input, options=opts)
    await get_queue().submit(job.id)
    return {"ok": True, "job_id": job.id, "status": job.status}


async def _write_change_key(*, job_id: str, semitones: float, **_kw) -> dict[str, Any]:
    """Re-render the instrumental in a new key via the existing pipeline."""
    from ..core.jobs import JobOptions, registry
    from ..core.queue import get_queue
    src = registry.get(job_id)
    if src is None:
        raise HTTPException(404, "job_not_found")
    opts = JobOptions(semitones=float(semitones))
    job = registry.create(input_str=src.input, options=opts)
    await get_queue().submit(job.id)
    return {"ok": True, "job_id": job.id, "semitones": float(semitones)}


async def _write_slow_down(*, job_id: str, tempo_ratio: float, **_kw) -> dict[str, Any]:
    from ..pipeline.transform import transform_audio  # noqa: F401  (sanity import)
    # The real /slowdown route lives in api/jobs.py and has its own
    # request schema; here we just return a marker that the chat layer
    # forwards the call. Detailed wiring is the M6 follow-up.
    return {
        "ok": True,
        "job_id": job_id,
        "tempo_ratio": float(tempo_ratio),
        "note": "Forwarded to /jobs/{id}/slowdown — see chat router dispatch.",
    }


async def _write_make_lead_sheet(*, job_id: str, stem_kind: str = "vocals", **_kw) -> dict[str, Any]:
    return {
        "ok": True,
        "job_id": job_id,
        "stem_kind": stem_kind,
        "note": "Forwarded to /jobs/{id}/score — see chat router dispatch.",
    }


async def _write_create_setlist(*, name: str, job_ids: list[str] | None = None, **_kw) -> dict[str, Any]:
    from ..api import setlists as setlists_api
    items = setlists_api._load()  # type: ignore[attr-defined]
    from ..api.setlists import _now  # type: ignore[attr-defined]
    sid = f"sl_{int(_now())}"
    new = {
        "id": sid,
        "name": str(name)[:120],
        "job_ids": [str(j) for j in (job_ids or [])],
        "created_at": _now(),
        "updated_at": _now(),
    }
    items.append(new)
    setlists_api._save(items)  # type: ignore[attr-defined]
    return {"ok": True, "setlist_id": sid, "name": new["name"]}


# -- catalog ----------------------------------------------------------------

CATALOG: list[ToolDescriptor] = [
    # read tools — instant execution
    ToolDescriptor(
        name="get_job_meta",
        mode="read",
        description="Look up a job's analysis metadata (title, key, BPM, status).",
        parameters={
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "Job id"}},
            "required": ["job_id"],
        },
        handler=_read_get_job_meta,
    ),
    ToolDescriptor(
        name="list_recent_jobs",
        mode="read",
        description="List the most recent Re:Chord jobs.",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}},
        },
        handler=_read_list_recent_jobs,
    ),
    ToolDescriptor(
        name="search_music_db",
        mode="read",
        description="Search the worship/music seed DB by title, artist, or partial lyrics.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
        handler=_read_search_music_db,
    ),
    ToolDescriptor(
        name="list_setlists",
        mode="read",
        description="List all setlists (named groups of jobs).",
        parameters={"type": "object", "properties": {}},
        handler=_read_list_setlists,
    ),
    ToolDescriptor(
        name="analyze_audio_url",
        mode="read",
        description=(
            "Download + analyze a URL for key, BPM, and meter ONLY. Use "
            "this whenever the user asks for a quick analysis ('이 곡 BPM "
            "알려줘', '키가 뭐야?', '박자는?') and supplies a YouTube / "
            "SoundCloud / direct-audio link. Returns within ~45 seconds, "
            "so you can answer in the same chat turn without making the "
            "user wait. NO stem separation, NO transcription, NO score — "
            "use ``request_create_job`` for those."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": "http(s) audio/video URL"},
            },
            "required": ["url"],
        },
        handler=_read_analyze_audio_url,
    ),
    ToolDescriptor(
        name="fetch_youtube_lyrics",
        mode="read",
        description=(
            "Pull verified Korean worship lyrics from YouTube. Worship teams "
            "(마커스 / 어노인팅 / 제이어스 / 위러브 / 예람 etc.) publish official "
            "lyrics in the video description or as CC/subtitles, both of "
            "which are written by the team itself. Call this BEFORE making "
            "up Korean translated lyrics whenever the seed DB has no "
            "verified `lyrics_lines` for the requested song. The query "
            "should include the song title + translator team name when "
            "known (e.g. 'Way Maker 마커스 워시 가사')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Song + team query"},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                "fetch_subtitles": {
                    "type": "boolean", "default": True,
                    "description": "Set false for description-only (faster).",
                },
            },
            "required": ["query"],
        },
        handler=_read_fetch_youtube_lyrics,
    ),
    ToolDescriptor(
        name="web_search",
        mode="read",
        description="Fall back to a web search (Tavily) for songs not in the seed DB.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "n": {"type": "integer", "minimum": 1, "maximum": 8, "default": 3},
            },
            "required": ["query"],
        },
        handler=_read_web_search,
    ),
    # write tools — require user confirmation
    ToolDescriptor(
        name="request_create_job",
        mode="write",
        description="Create a new Re:Chord job from a URL or uploaded file path.",
        parameters={
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "URL or local file path"},
                "options": {"type": "object", "description": "JobOptions overrides"},
            },
            "required": ["input"],
        },
        handler=_write_create_job,
        confirm_label_template="{input} 로 새 작업 생성",
    ),
    ToolDescriptor(
        name="request_change_key",
        mode="write",
        description="Re-render the job in a new key (semitone offset).",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "semitones": {"type": "number", "minimum": -12, "maximum": 12},
            },
            "required": ["job_id", "semitones"],
        },
        handler=_write_change_key,
        confirm_label_template="{job_id} 키를 {semitones} 반음 이동",
    ),
    ToolDescriptor(
        name="request_slow_down",
        mode="write",
        description="Pitch-preserving tempo change on an existing artifact.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "tempo_ratio": {"type": "number", "minimum": 0.5, "maximum": 2.0},
            },
            "required": ["job_id", "tempo_ratio"],
        },
        handler=_write_slow_down,
        confirm_label_template="{job_id} 템포 {tempo_ratio}× 변경",
    ),
    ToolDescriptor(
        name="request_make_lead_sheet",
        mode="write",
        description="Generate a lead-sheet score (SVG + PDF + MusicXML) for a stem.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "stem_kind": {"type": "string", "enum": ["vocals", "piano", "guitar", "bass", "drums", "other"], "default": "vocals"},
            },
            "required": ["job_id"],
        },
        handler=_write_make_lead_sheet,
        confirm_label_template="{job_id} 단선리드시트 생성 ({stem_kind})",
    ),
    ToolDescriptor(
        name="request_create_setlist",
        mode="write",
        description="Create a new named setlist (group of jobs).",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "job_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        },
        handler=_write_create_setlist,
        confirm_label_template="셋리스트 \"{name}\" 생성",
    ),
]

_BY_NAME: dict[str, ToolDescriptor] = {t.name: t for t in CATALOG}


def get_tool(name: str) -> ToolDescriptor | None:
    return _BY_NAME.get(name)


def openai_tools_schema() -> list[dict[str, Any]]:
    """Return the full catalog in OpenAI ``tools[]`` shape."""
    return [t.openai_schema() for t in CATALOG]


def render_tools_block(*, locale: str = "ko") -> str:
    """Compact human-readable description of the catalog, for the
    system prompt when function-calling isn't enabled (so the model can
    still reason about available actions in natural language)."""
    if locale == "en":
        header = (
            "Available tools (the user can confirm-and-run any of these — "
            "describe them in natural language when relevant):"
        )
    else:
        header = (
            "사용 가능한 도구 (사용자가 확인 후 실행할 수 있는 작업들 — "
            "관련 요청에 자연어로 안내하세요):"
        )
    lines = [header, ""]
    for t in CATALOG:
        tag = "📖 read" if t.mode == "read" else "✏️ write (확인 필요)"
        lines.append(f"- `{t.name}` [{tag}] — {t.description}")
    return "\n".join(lines).strip()


async def dispatch(name: str, args: dict[str, Any], *, allow_write: bool = False) -> dict[str, Any]:
    """Invoke a tool by name. Read-tool dispatch is always allowed; write
    tools require ``allow_write=True`` (used by the /execute endpoint to
    enforce the confirm gate).
    """
    desc = get_tool(name)
    if desc is None:
        raise HTTPException(404, f"unknown tool: {name}")
    if desc.mode == "write" and not allow_write:
        raise HTTPException(
            403,
            f"tool '{name}' requires user confirmation; use the /tools/{name}/execute endpoint",
        )
    if desc.handler is None:
        raise HTTPException(501, f"tool '{name}' has no handler")
    # Defensive: parse arguments via JSON Schema would be ideal, here we
    # just trust the caller (the chat router validates body shapes).
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"bad tool args: {e}") from e
    if not isinstance(args, dict):
        raise HTTPException(400, "tool args must be an object")
    return await desc.handler(**args)


__all__ = [
    "ToolDescriptor",
    "CATALOG",
    "get_tool",
    "openai_tools_schema",
    "render_tools_block",
    "dispatch",
]
