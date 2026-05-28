"""In-memory chat session registry.

Mirrors the existing JobRegistry pattern (backend/app/core/jobs.py) so the
Phase A → Phase B transition is the same swap-out: replace the underlying
dict with a SQLAlchemy session and the rest of the call sites stay intact.

History is trimmed per ``settings.chat_history_max_messages`` so the OpenAI
context window stays predictable.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .schemas import ChatAttachment, ChatMessage, JobContextSnapshot


def _now() -> float:
    return time.time()


def _gen_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:24]}"


@dataclass
class ChatSession:
    id: str
    owner_user_id: str
    title: str | None = None
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    history: list[ChatMessage] = field(default_factory=list)
    job_context_snapshot: JobContextSnapshot | None = None
    attachments: dict[str, ChatAttachment] = field(default_factory=dict)
    pending_tool_confirmations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def append(self, msg: ChatMessage, max_messages: int) -> None:
        self.history.append(msg)
        self.updated_at = _now()
        if len(self.history) > max_messages:
            # Keep the most recent N — older turns drop off. The system prompt
            # is rebuilt fresh on every turn, so we never lose persona/policy.
            self.history = self.history[-max_messages:]


class ChatSessionRegistry:
    """Thread-safe in-memory store keyed by session_id."""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str | None, owner_user_id: str) -> ChatSession:
        sid = session_id or _gen_id("sess_")
        with self._lock:
            sess = self._sessions.get(sid)
            if sess is None:
                sess = ChatSession(id=sid, owner_user_id=owner_user_id)
                self._sessions[sid] = sess
            return sess

    def get(self, session_id: str) -> ChatSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list_for_user(self, owner_user_id: str) -> list[ChatSession]:
        """Return every session belonging to a user, newest first."""
        with self._lock:
            mine = [s for s in self._sessions.values() if s.owner_user_id == owner_user_id]
        mine.sort(key=lambda s: s.updated_at, reverse=True)
        return mine

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def gc(self, max_age_sec: float) -> int:
        """Drop sessions idle longer than max_age_sec. Returns count removed."""
        cutoff = _now() - max_age_sec
        removed = 0
        with self._lock:
            stale = [sid for sid, s in self._sessions.items() if s.updated_at < cutoff]
            for sid in stale:
                self._sessions.pop(sid, None)
                removed += 1
        return removed


_REGISTRY: ChatSessionRegistry | None = None


def get_registry() -> ChatSessionRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ChatSessionRegistry()
    return _REGISTRY


__all__ = [
    "ChatSession",
    "ChatSessionRegistry",
    "get_registry",
    "_gen_id",
    "_now",
]
