"""OpenAI client wrapper for the chat service.

M1 implements a non-streaming completion. M2 swaps to ``stream=True`` and
relays deltas as SSE events. The lazy singleton lets the rest of the app
import this module even when ``OPENAI_API_KEY`` is empty.
"""

from __future__ import annotations

import re
from typing import Any, AsyncIterator

from fastapi import HTTPException, status

from ..config import settings
from .prompts import build_system_prompt
from .schemas import ChatMessage, JobContextSnapshot, Locale


_CLIENT = None  # lazy AsyncOpenAI instance


def _require_client():
    """Return the AsyncOpenAI singleton, or raise 503 if the SDK is missing
    or the API key is unset. We don't crash at import time so the rest of
    the API stays up when the chatbot is disabled.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY not configured; chatbot is disabled.",
        )
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="openai SDK not installed; run `pip install openai>=1.55`",
        ) from e
    _CLIENT = AsyncOpenAI(api_key=settings.openai_api_key)
    return _CLIENT


# Extract <confidence>…</confidence> from the assistant output so the
# frontend can render a ConfidenceBadge separately. The token stays in the
# raw message (for transparency) but the parsed value is also surfaced.
#
# Robust against the ways an LLM actually emits the value:
#   <confidence>0.85</confidence>     → 0.85
#   <confidence>0.9999</confidence>   → 0.9999 (multi-digit)
#   <confidence>85%</confidence>      → 0.85   (percent form)
#   <confidence> .7 </confidence>     → 0.7    (leading-dot, whitespace)
#   <confidence>1</confidence>        → 1.0
# When the token appears multiple times we take the *last* one (the model
# usually restates its final confidence at the end of the answer).
_CONFIDENCE_RE = re.compile(
    r"<confidence>\s*(?P<value>\d{0,3}(?:\.\d+)?)\s*(?P<pct>%?)\s*</confidence>",
    re.IGNORECASE,
)


def parse_confidence(text: str) -> float | None:
    if not text:
        return None
    matches = list(_CONFIDENCE_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]                  # last token wins
    raw = m.group("value")
    if raw in ("", "."):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    # Percent form ("85%") or a bare integer > 1 (the model wrote "85"
    # meaning 85%) → divide by 100.
    if m.group("pct") == "%" or v > 1.0:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def strip_confidence_token(text: str) -> str:
    """Remove the <confidence>…</confidence> token from display text.

    The raw value is surfaced separately via parse_confidence; the token
    itself shouldn't clutter the rendered chat bubble.
    """
    if not text:
        return text
    return _CONFIDENCE_RE.sub("", text).strip()


def _to_openai_messages(
    history: list[ChatMessage],
    user_text: str,
    locale: Locale,
    job_context: JobContextSnapshot | None,
    *,
    db_hits_block: str = "",
    korean_versions_block: str = "",
    web_results_block: str = "",
    tools_block: str = "",
) -> list[dict[str, Any]]:
    """Convert our session history + the new user turn into the OpenAI
    chat.completions ``messages`` array. System prompt is always rebuilt
    fresh so policy changes propagate instantly.
    """
    system = build_system_prompt(
        locale=locale,
        job_context=job_context,
        db_hits_block=db_hits_block,
        korean_versions_block=korean_versions_block,
        web_results_block=web_results_block,
        tools_block=tools_block,
    )
    msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in history:
        if m.role == "system":
            # We rebuild system fresh — drop any stored system messages so we
            # don't double up persona/policy.
            continue
        msgs.append({"role": m.role, "content": m.content})
    msgs.append({"role": "user", "content": user_text})
    return msgs


# Titles that are technically valid but carry no information. If the model
# returns one of these we discard it so the caller can fall back to "(첫
# 사용자 메시지 미리보기)" or retry on the next turn.
_TITLE_BLACKLIST_KO = {
    "제목없음", "제목 없음", "무제", "새 대화", "새대화", "새 채팅", "새채팅",
    "안녕하세요", "안녕", "반갑습니다", "테스트", "대화", "잡담", "질문", "문의",
}
_TITLE_BLACKLIST_EN = {
    "untitled", "untitled chat", "untitled conversation", "new chat", "new conversation",
    "conversation", "chat", "hello", "hi", "greetings", "test", "question", "inquiry",
}


def _is_meaningless_title(title: str, locale: Locale) -> bool:
    norm = title.strip().lower()
    if not norm or len(norm) < 2:
        return True
    if locale == "en":
        return norm in _TITLE_BLACKLIST_EN
    return title.strip() in _TITLE_BLACKLIST_KO or norm in _TITLE_BLACKLIST_EN


async def summarize_title(
    *,
    user_text: str,
    assistant_text: str,
    locale: Locale = "ko",
) -> str:
    """Generate a short conversation title that summarizes the substance
    of the first turn.

    Skips short/throwaway user messages (e.g. "안녕") that can't yet be
    summarized — the caller can retry later when the conversation has more
    content. Also rejects placeholder titles ("제목없음", "Hello") via the
    blacklist so they never get persisted.
    """
    # If the user's first turn is too short / generic to summarize, don't
    # waste a model call. The conversation list will fall back to "(no
    # title)" and we'll try again after a future turn.
    stripped = (user_text or "").strip()
    if len(stripped) < 4:
        return ""

    client = _require_client()
    if locale == "ko":
        system = (
            "사용자와 어시스턴트의 대화를 보고 한국어 제목을 만들어라.\n"
            "- 반드시 대화의 **구체적인 주제**(곡명, 가수명, 키/템포, 분석한 항목 등)를 담을 것\n"
            "- 14자 이내, 명사형, 이모지·인용부호·마침표 금지\n"
            "- 금지어: '제목없음', '새 대화', '안녕하세요', '대화', '질문', '문의', '테스트'\n"
            "- 단순 인사·잡담만 있고 주제가 없으면 정확히 빈 문자열만 출력\n"
            "예시:\n"
            "  사용자: \"Way Maker 키 알려줘\" → 제목: Way Maker 키\n"
            "  사용자: \"BTS 봄날 BPM\" → 제목: 봄날 BPM\n"
            "  사용자: \"안녕\" → 제목: (빈 문자열)\n"
        )
        user = f"사용자: {stripped[:400]}\n어시스턴트: {(assistant_text or '')[:500]}"
    else:
        system = (
            "Make a conversation title in English (≤ 6 words) summarizing the "
            "specific topic discussed (song name, artist, key/tempo, etc).\n"
            "- Noun phrase, no emoji, no quotes, no trailing punctuation\n"
            "- Banned: 'untitled', 'new chat', 'hello', 'conversation', 'question'\n"
            "- If the message is just a greeting with no substance, output an "
            "empty string only.\n"
            "Examples:\n"
            "  User: \"What key is Way Maker?\" → Title: Way Maker key\n"
            "  User: \"hello\" → Title: (empty)\n"
        )
        user = f"User: {stripped[:400]}\nAssistant: {(assistant_text or '')[:500]}"
    try:
        resp = await client.chat.completions.create(
            model=settings.openai_chat_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=24,
            temperature=0.2,
        )
        title = (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""

    # Strip wrapping punctuation the model sometimes adds despite the rules.
    for ch in ('"', "'", "「", "」", "『", "』", "(", ")", "[", "]", "<", ">", "*", "·", "—", "-"):
        title = title.strip(ch).strip()
    # Drop a leading "제목:" / "Title:" label if the model echoed it.
    for prefix in ("제목:", "제목 :", "Title:", "title:"):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
    # Final blacklist + length sanity check.
    if _is_meaningless_title(title, locale):
        return ""
    return title[:60]


async def complete_turn(
    *,
    history: list[ChatMessage],
    user_text: str,
    locale: Locale = "ko",
    job_context: JobContextSnapshot | None = None,
    db_hits_block: str = "",
    korean_versions_block: str = "",
    web_results_block: str = "",
    tools_block: str = "",
) -> str:
    """Non-streaming completion (M1). Returns the assistant's full reply.

    Kept for tests / fallback paths. Production traffic uses ``stream_turn``.
    """
    client = _require_client()
    messages = _to_openai_messages(
        history, user_text, locale, job_context,
        db_hits_block=db_hits_block,
        korean_versions_block=korean_versions_block,
        web_results_block=web_results_block,
        tools_block=tools_block,
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.openai_chat_model,
            messages=messages,
            max_tokens=settings.openai_max_tokens,
            temperature=settings.openai_temperature,
        )
    except Exception as e:
        # Surface a clean 502 with the upstream message trimmed.
        detail = f"OpenAI upstream error: {type(e).__name__}: {str(e)[:300]}"
        raise HTTPException(status_code=502, detail=detail) from e
    if not resp.choices:
        raise HTTPException(status_code=502, detail="OpenAI returned no choices.")
    content = resp.choices[0].message.content or ""
    return content


async def stream_turn(
    *,
    history: list[ChatMessage],
    user_text: str,
    locale: Locale = "ko",
    job_context: JobContextSnapshot | None = None,
    db_hits_block: str = "",
    korean_versions_block: str = "",
    web_results_block: str = "",
    tools_block: str = "",
) -> AsyncIterator[str]:
    """Streaming completion (M2). Yields incremental text chunks (deltas).

    Caller is responsible for buffering the full reply (to extract the
    <confidence> token and persist the assistant message). Errors are
    raised as HTTPException so the SSE generator can emit an 'error' frame.
    """
    client = _require_client()
    messages = _to_openai_messages(
        history, user_text, locale, job_context,
        db_hits_block=db_hits_block,
        korean_versions_block=korean_versions_block,
        web_results_block=web_results_block,
        tools_block=tools_block,
    )
    try:
        stream = await client.chat.completions.create(
            model=settings.openai_chat_model,
            messages=messages,
            max_tokens=settings.openai_max_tokens,
            temperature=settings.openai_temperature,
            stream=True,
        )
    except Exception as e:
        detail = f"OpenAI upstream error: {type(e).__name__}: {str(e)[:300]}"
        raise HTTPException(status_code=502, detail=detail) from e

    try:
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                yield piece
    except Exception as e:
        detail = f"OpenAI stream error: {type(e).__name__}: {str(e)[:300]}"
        raise HTTPException(status_code=502, detail=detail) from e


__all__ = ["complete_turn", "stream_turn", "parse_confidence",
           "strip_confidence_token", "summarize_title"]
