"""Pydantic schemas for the chat API surface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Role = Literal["user", "assistant", "system"]
Locale = Literal["ko", "en"]


class JobContextSnapshot(BaseModel):
    """Lightweight summary of the current Job (sent by the client when the
    user is on a Job page) so the assistant can answer "what key is this in?"
    without having to call back for analysis.

    The client should re-send this every turn so the assistant always sees
    the *current* state — if the user edits the meter, transposes the key,
    or corrects a chord mid-conversation, the next turn's snapshot reflects
    it and the assistant won't answer from stale analysis.
    """

    job_id: str
    title: str | None = None
    key_name: str | None = None
    bpm: float | None = None
    time_signature: str | None = None       # e.g. "4/4", "6/8" — user-editable
    chord_summary: str | None = None
    section_summary: str | None = None
    lyrics_excerpt: str | None = None
    # Optional richer context the frontend can attach.
    modulations: str | None = None          # e.g. "마지막 후렴 +1 반음"
    available_stems: str | None = None       # e.g. "vocals, drums, bass, ..."
    transpose_semitones: int | None = None   # current user transposition


class ChatAttachment(BaseModel):
    id: str
    kind: Literal["upload", "url", "voice"]
    filename: str | None = None
    url: str | None = None
    path: str | None = None
    quick_analysis: dict[str, Any] | None = None


class ChatMessage(BaseModel):
    id: str
    role: Role
    content: str
    created_at: float
    attachments: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class ChatTurnRequest(BaseModel):
    """Body of POST /chat/sessions/{id}/messages."""

    text: str = Field(..., min_length=1, max_length=8000)
    attachment_ids: list[str] = Field(default_factory=list)
    job_context: JobContextSnapshot | None = None
    locale: Locale = "ko"


class ChatTurnResponse(BaseModel):
    """Non-streaming response (M1). M2 switches to SSE."""

    message: ChatMessage
    confidence: float | None = None


class SessionCreateRequest(BaseModel):
    session_id: str | None = None  # client-generated UUID echoed back


class SessionInfo(BaseModel):
    id: str
    title: str | None = None
    created_at: float
    updated_at: float
    message_count: int
    last_message_preview: str | None = None


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
