"""Chat API — OpenAI-powered worship/music assistant.

M1 implements:
  POST   /chat/sessions             create or reuse a session
  GET    /chat/sessions/{id}        fetch conversation history
  POST   /chat/sessions/{id}/messages  non-streaming turn (M2 -> SSE)
  DELETE /chat/sessions/{id}        drop a session

Later milestones add attach, voice, and tool-execute endpoints. Auth
dependency runs from day 1 — Phase A returns GuestUser so call sites stay
identical when Phase B lights up auth.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..auth.auth import User, get_current_user
from ..chat.attachments import (
    ingest_url_for_chat,
    quick_analyze,
    render_attachment_block,
    stage_uploaded_file,
)
from ..chat.korean_translation import (
    build_full_lyrics_block,
    build_korean_versions_block,
    build_lyrics_policy_block,
    detect_full_lyrics_request,
    detect_translation_intent,
)
from ..chat.music_db import get_db, render_hits_block
from ..chat.openai_client import (
    parse_confidence,
    stream_turn,
    strip_confidence_token,
    summarize_title,
)
from ..chat.ratelimit import get_limiter
from ..core.ratelimit import client_ip, chat_global_daily, chat_ip_limiter
from ..chat.tools import dispatch as dispatch_tool
from ..chat.tools import get_tool, render_tools_block
from ..chat.schemas import (
    ChatAttachment,
    ChatMessage,
    ChatTurnRequest,
    SessionCreateRequest,
    SessionInfo,
    SessionPatch,
)
from ..chat.sessions import ChatSession, _gen_id, _now, get_registry
from ..chat.web_search import get_search_adapter, render_web_results_block
from ..config import settings
from ..pipeline.ingest import is_url


router = APIRouter(prefix="/chat", tags=["chat"])


# Per-process YouTube-lyrics cache. fetch_youtube_lyrics is ~15-30s per
# call (yt-dlp metadata + subtitle download), so we memoise by
# (song_title, top_translator_team) for the lifetime of the process.
# Bounded ad-hoc to avoid an unbounded dict; entries are tiny so the cap
# is large.
_YT_CACHE: dict[tuple[str, str], list] = {}
_YT_CACHE_MAX = 256


async def _ytlyrics_cached(title: str, team: str) -> list:
    """Cached wrapper around ``fetch_youtube_lyrics`` for chat-turn use.

    Runs the sync yt-dlp call in the default executor so the chat
    response keeps streaming. Cache key is the normalised
    (title, top translator team) pair; the chat handler always passes
    the canonical title from the seed DB so cache hit rate is high
    across repeated user queries about the same song.
    """
    key = (title.strip().lower(), team.strip().lower())
    if key in _YT_CACHE:
        return _YT_CACHE[key]
    from ..chat.youtube_lyrics import fetch_youtube_lyrics
    query = f"{title} {team} 가사".strip()
    loop = asyncio.get_running_loop()
    try:
        hits = await loop.run_in_executor(
            None, lambda: fetch_youtube_lyrics(query, top_n=2, fetch_subtitles=True),
        )
    except Exception:
        hits = []
    if len(_YT_CACHE) >= _YT_CACHE_MAX:
        # crude LRU: drop an arbitrary entry. Cache is single-process and
        # entries are cheap to refetch, so we don't need a fancy data
        # structure.
        _YT_CACHE.pop(next(iter(_YT_CACHE)))
    _YT_CACHE[key] = hits
    return hits


def _session_info(s: ChatSession) -> SessionInfo:
    """Convert a ChatSession into the lightweight list-view DTO."""
    preview: str | None = None
    for msg in reversed(s.history):
        if msg.role in ("user", "assistant"):
            preview = (msg.content or "").strip()
            if len(preview) > 80:
                preview = preview[:80] + "…"
            break
    return SessionInfo(
        id=s.id,
        title=s.title,
        created_at=s.created_at,
        updated_at=s.updated_at,
        message_count=len(s.history),
        last_message_preview=preview,
    )


async def _autotitle_after_first_turn(session_id: str, locale: str) -> None:
    """Background helper — generate a conversation title that summarizes
    the substance of what the user has been asking about.

    Runs after the main turn so we don't block the user-facing response.
    Combines up to the last 3 user messages plus the latest assistant
    reply, so a title becomes more accurate as the conversation grows
    (a one-word greeting can't be summarized, but the same session 2
    turns later usually can be).
    """
    sess = get_registry().get(session_id)
    if sess is None or sess.title:
        return
    user_msgs = [m for m in sess.history if m.role == "user"]
    asst_msgs = [m for m in sess.history if m.role == "assistant"]
    if not user_msgs or not asst_msgs:
        return
    combined_user = "\n".join(m.content for m in user_msgs[-3:])
    last_assistant = asst_msgs[-1].content
    try:
        title = await summarize_title(
            user_text=combined_user,
            assistant_text=last_assistant,
            locale=locale if locale in ("ko", "en") else "ko",
        )
    except Exception:
        return
    # Re-fetch in case the session was deleted while we were computing.
    sess = get_registry().get(session_id)
    if sess is not None and title and not sess.title:
        sess.title = title
        sess.updated_at = _now()


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    user: User = Depends(get_current_user),
) -> list[SessionInfo]:
    """List the current user's conversations, newest first.

    Conversations are stored in-memory (Phase A); the client mirrors the
    list in localStorage so a hard reload doesn't lose the index when the
    backend restarts.
    """
    return [_session_info(s) for s in get_registry().list_for_user(user.id)]


@router.post("/sessions", response_model=SessionInfo)
async def create_session(
    body: SessionCreateRequest | None = None,
    user: User = Depends(get_current_user),
) -> SessionInfo:
    """Create or reuse a session.

    The client passes a UUID as ``session_id``. We reuse if present,
    create otherwise. Passing no id (or ``null``) always creates a new
    conversation — that's the "New chat" button path.
    """
    reg = get_registry()
    sid = (body.session_id if body else None) or None
    sess = reg.get_or_create(sid, owner_user_id=user.id)
    return _session_info(sess)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    sess = get_registry().get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="not your session")
    return {
        "id": sess.id,
        "title": sess.title,
        "created_at": sess.created_at,
        "updated_at": sess.updated_at,
        "history": [m.model_dump() for m in sess.history],
    }


@router.patch("/sessions/{session_id}", response_model=SessionInfo)
async def patch_session(
    session_id: str,
    body: SessionPatch,
    user: User = Depends(get_current_user),
) -> SessionInfo:
    """Update conversation metadata (currently: title rename)."""
    sess = get_registry().get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    if sess.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="not your session")
    if body.title is not None:
        sess.title = body.title.strip() or None
        sess.updated_at = _now()
    return _session_info(sess)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    sess = get_registry().get(session_id)
    if sess is None:
        return {"ok": True, "removed": False}
    if sess.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="not your session")
    get_registry().delete(session_id)
    return {"ok": True, "removed": True}


# ---- M5: attachments --------------------------------------------------------


def _ensure_owned(session_id: str, user_id: str) -> ChatSession:
    sess = get_registry().get_or_create(session_id, owner_user_id=user_id)
    if sess.owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="not your session")
    return sess


async def _record_attachment(
    sess: ChatSession,
    *,
    kind: str,
    filename: str | None,
    url: str | None,
    path: str | None,
    quick_analysis: dict | None,
) -> ChatAttachment:
    aid = _gen_id("att_")
    att = ChatAttachment(
        id=aid,
        kind=kind,  # type: ignore[arg-type]
        filename=filename,
        url=url,
        path=path,
        quick_analysis=quick_analysis,
    )
    sess.attachments[aid] = att
    sess.updated_at = _now()
    return att


@router.post("/sessions/{session_id}/attach/upload", response_model=ChatAttachment)
async def attach_upload(
    session_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> ChatAttachment:
    """Stage a multipart audio upload and run a lightweight key/BPM
    analysis. Returns the attachment record; the client passes the id
    back in the next ``/messages`` call to surface the analysis to the
    assistant.
    """
    sess = _ensure_owned(session_id, user.id)
    attach_id_seed = _gen_id("staging_")
    try:
        path = await stage_uploaded_file(session_id, attach_id_seed, file)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"upload failed: {e}") from e
    qa = await quick_analyze(path)
    return await _record_attachment(
        sess,
        kind="upload",
        filename=file.filename,
        url=None,
        path=str(path),
        quick_analysis=qa,
    )


# ---- M6: tool calling -------------------------------------------------------


@router.get("/tools")
async def list_tools(user: User = Depends(get_current_user)) -> dict:
    """Public catalog of tools the chatbot can invoke. The frontend uses
    this to render confirm-card labels and to gate UI affordances.
    """
    from ..chat.tools import CATALOG
    return {
        "tools": [
            {
                "name": t.name,
                "mode": t.mode,
                "description": t.description,
                "parameters": t.parameters,
                "confirm_label_template": t.confirm_label_template,
            }
            for t in CATALOG
        ],
    }


@router.post("/sessions/{session_id}/tools/{tool_name}/execute")
async def execute_tool(
    session_id: str,
    tool_name: str,
    body: dict = Body(default_factory=dict),
    user: User = Depends(get_current_user),
) -> dict:
    """Run a tool after the user has confirmed it in the UI.

    Read tools also flow through this endpoint when the client wants to
    invoke them directly (rare — usually the LLM emits read-tool calls
    inline). Write tools ALWAYS require this endpoint (the LLM cannot
    bypass the confirm gate).
    """
    sess = _ensure_owned(session_id, user.id)
    desc = get_tool(tool_name)
    if desc is None:
        raise HTTPException(404, f"unknown tool: {tool_name}")
    args = body.get("args") if isinstance(body, dict) else None
    args = args if isinstance(args, dict) else {}
    try:
        result = await dispatch_tool(tool_name, args, allow_write=True)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"tool execution failed: {type(e).__name__}: {str(e)[:200]}") from e
    # Record the invocation on the session so the next chat turn can
    # reference it via the regular message history.
    invocation_id = _gen_id("tinv_")
    sess.pending_tool_confirmations[invocation_id] = {
        "tool": tool_name,
        "args": args,
        "result": result,
        "executed_at": _now(),
    }
    sess.updated_at = _now()
    return {"ok": True, "invocation_id": invocation_id, "tool": tool_name, "result": result}


# ---- M7: voice transcription ------------------------------------------------


@router.post("/sessions/{session_id}/voice")
async def transcribe_voice(
    session_id: str,
    audio: UploadFile = File(...),
    locale: str = "ko",
    user: User = Depends(get_current_user),
) -> dict:
    """Transcribe a recorded mic blob to text using the local
    faster-whisper turbo model with worship-domain priming.

    Audio leaves the local box only as needed by ``faster_whisper`` —
    we don't ship the blob to OpenAI. The temp file is deleted after
    transcription so we don't accumulate voice clips on disk.
    """
    sess = _ensure_owned(session_id, user.id)
    attach_id_seed = _gen_id("voice_")
    try:
        path = await stage_uploaded_file(session_id, attach_id_seed, audio)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"upload failed: {e}") from e

    # Run faster-whisper in a thread pool — librosa/CT2 are sync.
    def _run() -> dict:
        try:
            from ..pipeline.lyrics import transcribe_lyrics
            out_dir = path.parent
            domain = "worship_ko" if locale == "ko" else "worship_en"
            r = transcribe_lyrics(
                audio_path=path,
                out_dir=out_dir,
                language="ko" if locale == "ko" else "auto",
                domain_prompt=domain,
                model_size="turbo",
                use_cuda=True,
            )
            text = " ".join(w.word for w in r.words).strip()
            return {
                "ok": True,
                "text": text,
                "language": r.language,
                "confidence": round(r.avg_confidence, 3),
                "domain_prompt": domain,
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    result = await asyncio.to_thread(_run)
    # Best-effort: delete the temp audio so we don't keep voice on disk.
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    if not result.get("ok"):
        raise HTTPException(500, result.get("error") or "voice transcription failed")
    sess.updated_at = _now()
    return result


@router.post("/sessions/{session_id}/attach/url", response_model=ChatAttachment)
async def attach_url(
    session_id: str,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
) -> ChatAttachment:
    """Download a remote URL (yt-dlp) and analyze. Body: ``{"url": "..."}``."""
    sess = _ensure_owned(session_id, user.id)
    url = (body or {}).get("url") or ""
    if not isinstance(url, str) or not is_url(url):
        raise HTTPException(status_code=400, detail="invalid or missing url")
    attach_id_seed = _gen_id("staging_")
    try:
        path, title = await ingest_url_for_chat(session_id, attach_id_seed, url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"ingest failed: {e}") from e
    qa = await quick_analyze(path)
    if title:
        qa["title"] = title
    return await _record_attachment(
        sess,
        kind="url",
        filename=title or None,
        url=url,
        path=str(path),
        quick_analysis=qa,
    )


def _sse(event_type: str, payload: dict) -> bytes:
    """Encode one Server-Sent Event frame.

    We put the type *inside* the JSON payload rather than using the SSE
    ``event:`` header so the client can stay on a generic JSON parser.
    """
    data = json.dumps({"type": event_type, **payload}, ensure_ascii=False)
    return f"data: {data}\n\n".encode("utf-8")


@router.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: str,
    body: ChatTurnRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    """M2 streaming turn — returns ``text/event-stream``.

    Event types (all framed as ``data: {"type": ..., ...}``):
      - ``delta``       {"text": str}          partial assistant content
      - ``confidence``  {"value": float}       parsed from <confidence>
      - ``message``     {"message": ChatMessage}  final persisted message
      - ``error``       {"detail": str}        upstream / internal failure
      - ``done``        {}                     stream complete
    """
    reg = get_registry()
    sess = reg.get_or_create(session_id, owner_user_id=user.id)
    if sess.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="not your session")

    # Public-endpoint cost guard: a session is free to mint, so the
    # per-session limit below is bypassable. Cap per-IP and globally per-day
    # so a bot scraping the domain can't run up the OpenAI bill.
    ip = client_ip(request)
    ok_ip, ra_ip = chat_ip_limiter.allow(ip)
    if not ok_ip:
        raise HTTPException(
            status_code=429,
            detail={"reason": "rate_limited", "retry_after": round(ra_ip, 1)},
            headers={"Retry-After": str(int(ra_ip) + 1)},
        )
    ok_global, _ = chat_global_daily.allow("global")
    if not ok_global:
        raise HTTPException(
            status_code=429,
            detail={"reason": "daily_quota",
                    "message": "오늘 전체 챗봇 사용량 한도에 도달했어요. 내일 다시 시도해주세요."},
        )

    # Rate-limit BEFORE we accept the message into history. Hitting 429 at
    # this layer means a plain HTTP error (the client renders a toast),
    # which is friendlier than an SSE 'error' frame mid-stream.
    allowed, retry_after = get_limiter().check(session_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"reason": "rate_limited", "retry_after": round(retry_after, 1)},
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    if body.job_context is not None:
        sess.job_context_snapshot = body.job_context

    user_msg = ChatMessage(
        id=_gen_id("msg_"),
        role="user",
        content=body.text,
        created_at=_now(),
        attachments=body.attachment_ids,
    )
    sess.append(user_msg, max_messages=settings.chat_history_max_messages)
    # Snapshot the history we'll send to OpenAI BEFORE we append the
    # assistant turn so we don't include the in-progress reply.
    history_snapshot = list(sess.history[:-1])
    locale = body.locale

    # ──────────────────────────────────────────────────────────────────
    # URL + quick-analysis intent → run the lite analyzer up front so the
    # LLM can answer in the same turn instead of stalling on "분석 중...".
    # OpenAI function-calling isn't wired through stream_turn yet, so the
    # handler does the dispatch for the model.
    # ──────────────────────────────────────────────────────────────────
    audio_analysis_block = ""
    try:
        import re as _re
        urls = _re.findall(r"https?://\S+", body.text or "")
        quick_words = (
            "bpm", "BPM", "템포", "tempo", "박자", "meter",
            "time signature", "타임시그너처", "키", "key ", "조성",
        )
        if urls and any(w in (body.text or "") for w in quick_words):
            from ..chat.tools import _read_analyze_audio_url  # type: ignore
            quick = await _read_analyze_audio_url(url=urls[0])
            if quick.get("ok"):
                audio_analysis_block = (
                    "[URL 분석 결과 — 챗봇이 즉시 madmom으로 분석한 값입니다. "
                    "아래 수치를 그대로 사용자에게 답변하세요. "
                    "추가 변환(분리/악보) 안내는 사용자가 요청할 때만 합니다.]\n"
                    f"- URL: {urls[0]}\n"
                    f"- 곡 제목: {quick.get('title')}\n"
                    f"- 길이: {quick.get('duration_sec', 0):.1f} s\n"
                    f"- Key: {quick.get('key_name')} "
                    f"(confidence {quick.get('key_confidence', 0):.2f})\n"
                    f"- BPM: {quick.get('bpm', 0):.1f} "
                    f"(confidence {quick.get('bpm_confidence', 0):.2f})\n"
                    f"- 박자: {quick.get('time_signature')} "
                    f"(meter={quick.get('meter')}, "
                    f"compound={quick.get('is_compound')})\n"
                    f"- 다운비트 개수: {quick.get('downbeat_count', 0)}"
                )
            else:
                audio_analysis_block = (
                    "[URL 분석 시도했으나 실패. 사용자에게 사과하고 "
                    f"다음 에러를 짧게 전달하세요: {quick.get('error', '?')}]"
                )
    except Exception as _e:  # never block the chat response
        audio_analysis_block = ""

    # Music seed DB lookup — runs only when the user's message has enough
    # content to be worth searching (so 1-2 char small talk doesn't waste
    # rapidfuzz cycles). Hits are inlined into the system prompt; the LLM
    # decides whether to use them.
    db_hits_block = ""
    korean_versions_block = ""
    lyrics_policy_block = ""
    web_results_block = ""
    attachment_block = ""
    hits = []
    if len((body.text or "").strip()) >= 4:
        try:
            hits = get_db().search(body.text, top_k=5, min_score=0.3)
            db_hits_block = render_hits_block(hits, locale=locale)
        except Exception:
            hits = []
            db_hits_block = ""

    # M4: detect Korean-translation intent + full-lyrics override and
    # inject the matching scaffolding blocks. Both blocks are empty
    # strings when not triggered, so the prompt stays compact for chit-chat.
    crosscheck_block = ""
    if detect_translation_intent(body.text) and hits:
        korean_versions_block = build_korean_versions_block(hits, locale=locale)
        # DB ↔ YouTube cross-validation. Worship-team channels publish
        # official Korean lyrics in the video description / CC; comparing
        # them against the DB catches both seed-DB typos and YouTube auto-
        # caption errors. Only runs on the top hit to keep latency bounded.
        try:
            from ..chat.youtube_lyrics import fetch_youtube_lyrics
            from ..chat.lyrics_crosscheck import (
                cross_check, report_to_prompt_block,
            )
            top = hits[0]
            rec = getattr(top, "record", None)
            kvs_raw = getattr(rec, "korean_versions", None) if rec else None
            title = getattr(rec, "primary_title", "") if rec else ""
            if kvs_raw:
                kvs_dicts = [
                    {"translator_team": getattr(kv, "translator_team", ""),
                     "lyrics_lines": getattr(kv, "lyrics_lines", []) or []}
                    for kv in kvs_raw
                ]
                # One YouTube fetch per chat turn (the query already pins
                # the song). Cached by (title, top team) below.
                top_team = kvs_dicts[0]["translator_team"] if kvs_dicts else ""
                yt_hits = await _ytlyrics_cached(title, top_team)
                report = cross_check(kvs_dicts, yt_hits, title=title)
                crosscheck_block = report_to_prompt_block(report, locale=locale)
        except Exception:
            # Cross-check is best-effort; never block the chat response.
            crosscheck_block = ""
    full_lyrics_block = ""
    if (
        settings.chat_lyrics_full_on_request
        and detect_full_lyrics_request(body.text)
    ):
        lyrics_policy_block = build_lyrics_policy_block(
            full_lyrics=True, locale=locale,
        )
        if hits:
            # Inject lyrics_full from any matched record that carries it
            # (public-domain hymns, licensed songs). Copyrighted records
            # only have lyrics_lines so this block stays compact.
            full_lyrics_block = build_full_lyrics_block(hits, locale=locale)

    # M5: web-search fallback. When seed DB is weak/empty AND the user
    # query looks like a song/artist question (≥ 8 chars), call Tavily.
    weak_hits = (not hits) or (max((h.score for h in hits), default=0.0) < 0.5)
    if weak_hits and len((body.text or "").strip()) >= 8:
        try:
            web_hits = await get_search_adapter().search(body.text, n=3)
            web_results_block = render_web_results_block(web_hits, locale=locale)
        except Exception:
            web_results_block = ""

    # M5: attachment summaries — the client passes attachment_ids from
    # POST /attach/upload or /attach/url; we look them up in the session
    # store and render their quick_analysis into the system prompt.
    if body.attachment_ids:
        atts: list[dict] = []
        for aid in body.attachment_ids:
            att = sess.attachments.get(aid)
            if att is not None:
                atts.append(att.model_dump())
        if atts:
            attachment_block = render_attachment_block(atts, locale=locale)

    async def generator():
        buffer = ""
        try:
            # Concatenate attachment + lyrics-policy + tool-catalog into
            # the tools slot — all three are instruction-style blocks.
            # Tools are listed in natural-language form here so the model
            # can reason about available actions even before OpenAI
            # function-calling integration lands (planned M6 follow-up).
            tools_catalog_block = (
                render_tools_block(locale=locale)
                if settings.chat_tool_calling_enabled
                else ""
            )
            extra_block = "\n\n".join(
                b for b in (
                    audio_analysis_block,
                    attachment_block,
                    lyrics_policy_block,
                    full_lyrics_block,
                    crosscheck_block,
                    tools_catalog_block,
                ) if b
            )
            async for piece in stream_turn(
                history=history_snapshot,
                user_text=body.text,
                locale=locale,
                job_context=sess.job_context_snapshot,
                db_hits_block=db_hits_block,
                korean_versions_block=korean_versions_block,
                web_results_block=web_results_block,
                tools_block=extra_block,
            ):
                buffer += piece
                yield _sse("delta", {"text": piece})
        except HTTPException as e:
            # OpenAI failure — surface as SSE 'error' and stop.
            detail = e.detail if isinstance(e.detail, str) else str(e.detail)
            # Roll the user message back so the next retry doesn't double-up.
            try:
                if sess.history and sess.history[-1].id == user_msg.id:
                    sess.history.pop()
            except Exception:
                pass
            yield _sse("error", {"detail": detail, "status": e.status_code})
            yield _sse("done", {})
            return
        except Exception as e:  # noqa: BLE001
            try:
                if sess.history and sess.history[-1].id == user_msg.id:
                    sess.history.pop()
            except Exception:
                pass
            yield _sse("error", {"detail": f"{type(e).__name__}: {str(e)[:200]}"})
            yield _sse("done", {})
            return

        # Parse confidence from the raw buffer, then strip the token so the
        # canonical (stored + re-rendered) message doesn't show the raw
        # <confidence> markup. The streamed deltas may have briefly shown
        # it; the final "message" event replaces the bubble with clean text.
        conf = parse_confidence(buffer)
        clean_content = strip_confidence_token(buffer)

        assistant_msg = ChatMessage(
            id=_gen_id("msg_"),
            role="assistant",
            content=clean_content,
            created_at=_now(),
        )
        sess.append(assistant_msg, max_messages=settings.chat_history_max_messages)

        if conf is not None:
            yield _sse("confidence", {"value": conf})

        yield _sse("message", {"message": assistant_msg.model_dump()})

        # Background auto-title — same logic as M1.1, just lifted here.
        if not sess.title:
            asyncio.create_task(_autotitle_after_first_turn(sess.id, locale))

        yield _sse("done", {})

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        # Nginx / some proxies buffer SSE by default — disable that.
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(generator(), media_type="text/event-stream", headers=headers)
