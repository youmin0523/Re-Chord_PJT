"""SQLAlchemy 2.x table definitions (Phase B SaaS).

Mirrors the JSON/in-memory shapes from Phase A so migration is a 1:1
copy when the time comes. Tables:

    users         — Clerk/Supabase user records (id = external_id)
    jobs          — current registry.Job
    setlists      — current setlists JSON store
    setlist_jobs  — many-to-many (preserves order via ``position``)
    notes         — current notes JSON store (per-job rehearsal notes)
    aux_patches   — user-uploaded reference patches for AUX classifier

All FKs use UUID/string keys to interoperate with Clerk/Supabase IDs
without needing a translation table. The Job model deliberately mirrors
JobOptions as a JSONB column rather than spreading options across
typed columns — JobOptions evolves often and we don't want a migration
per option.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    from sqlalchemy import (
        BigInteger, Boolean, DateTime, Float, ForeignKey, Integer,
        JSON, String, Text, func,
    )
    from sqlalchemy.orm import (
        DeclarativeBase, Mapped, mapped_column, relationship,
    )
    _HAS_SQLALCHEMY = True
except ImportError:
    # Allow this module to import (for tools, IDE) even when SQLAlchemy
    # isn't installed in the current env. All runtime use requires it.
    _HAS_SQLALCHEMY = False


if _HAS_SQLALCHEMY:
    class Base(DeclarativeBase):
        """Common base for all ORM models — single MetaData."""

    class User(Base):
        __tablename__ = "users"
        id:           Mapped[str] = mapped_column(String(64), primary_key=True)
        email:        Mapped[str | None] = mapped_column(String(255), nullable=True)
        display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
        created_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
        # Soft-delete flag — we never hard-delete user rows (audit / billing).
        is_active:    Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    class Job(Base):
        __tablename__ = "jobs"
        id:           Mapped[str] = mapped_column(String(32), primary_key=True)
        user_id:      Mapped[str | None] = mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
        )
        # Originally URL or local file path; on SaaS this becomes an
        # opaque storage key (R2 / S3 object URL).
        input:        Mapped[str] = mapped_column(Text, nullable=False)
        status:       Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
        stage:        Mapped[str] = mapped_column(String(32), default="", nullable=False)
        progress:     Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        message:      Mapped[str] = mapped_column(Text, default="", nullable=False)
        error:        Mapped[str | None] = mapped_column(Text, nullable=True)

        # JobOptions snapshot at submission time.
        options:      Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
        # Free-form metadata bag (key/BPM/quality/durations/…).
        meta:         Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
        # artifact_key → object URL.
        artifacts:    Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)

        created_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
        started_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        finished_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

        notes:        Mapped[list["Note"]] = relationship(
            back_populates="job", cascade="all, delete-orphan",
        )
        setlists:     Mapped[list["SetlistJob"]] = relationship(
            back_populates="job", cascade="all, delete-orphan",
        )

    class Setlist(Base):
        __tablename__ = "setlists"
        id:           Mapped[str] = mapped_column(String(32), primary_key=True)
        user_id:      Mapped[str | None] = mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
        )
        name:         Mapped[str] = mapped_column(String(160), nullable=False)
        created_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
        updated_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
            nullable=False,
        )
        jobs:         Mapped[list["SetlistJob"]] = relationship(
            back_populates="setlist", cascade="all, delete-orphan",
            order_by="SetlistJob.position",
        )

    class SetlistJob(Base):
        """M:N row with explicit ordering — ``position`` preserves setlist order."""
        __tablename__ = "setlist_jobs"
        setlist_id:   Mapped[str] = mapped_column(
            ForeignKey("setlists.id", ondelete="CASCADE"), primary_key=True,
        )
        job_id:       Mapped[str] = mapped_column(
            ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True,
        )
        position:     Mapped[int] = mapped_column(Integer, nullable=False)

        setlist:      Mapped[Setlist] = relationship(back_populates="jobs")
        job:          Mapped[Job] = relationship(back_populates="setlists")

    class Note(Base):
        __tablename__ = "notes"
        id:           Mapped[str] = mapped_column(String(32), primary_key=True)
        job_id:       Mapped[str] = mapped_column(
            ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True,
        )
        text:         Mapped[str] = mapped_column(Text, nullable=False)
        kind:         Mapped[str] = mapped_column(String(16), default="note", nullable=False)
        start_sec:    Mapped[float | None] = mapped_column(Float, nullable=True)
        end_sec:      Mapped[float | None] = mapped_column(Float, nullable=True)
        created_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
        updated_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
            nullable=False,
        )
        job:          Mapped[Job] = relationship(back_populates="notes")

    class UserConsent(Base):
        """User consent log for ToS / privacy policy / age / marketing.

        One row PER user × consent_type × policy version. Old rows stay
        forever (PIPA audit trail). When a user revokes, we set
        ``revoked_at`` instead of deleting.

        ``ip_address`` is stored as String not INET so SQLite (dev /
        tests) can hold it too; Postgres will accept either.
        """
        __tablename__ = "user_consents"
        id:           Mapped[int] = mapped_column(
            BigInteger, primary_key=True, autoincrement=True,
        )
        user_id:      Mapped[str] = mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        )
        # tos | privacy | intl_transfer | age_14 | copyright_self | marketing
        consent_type: Mapped[str] = mapped_column(String(32), nullable=False)
        # Policy version (e.g. "2026-05-28-v0.1") — see docs/legal/*.md.
        version:      Mapped[str] = mapped_column(String(40), nullable=False)
        granted:      Mapped[bool] = mapped_column(Boolean, nullable=False)
        granted_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
        revoked_at:   Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True,
        )
        # Best-effort consent provenance (PIPA evidentiary value).
        ip_address:   Mapped[str | None] = mapped_column(String(64), nullable=True)
        user_agent:   Mapped[str | None] = mapped_column(Text, nullable=True)

    class AuxPatch(Base):
        """User-uploaded reference patch for the AUX classifier.

        ``embedding`` is a 512-dim CLAP vector serialised as JSON list.
        For Phase B we'll likely add a pgvector column instead — keep
        the JSON shape for now to keep migrations boring.
        """
        __tablename__ = "aux_patches"
        id:           Mapped[str] = mapped_column(String(32), primary_key=True)
        user_id:      Mapped[str] = mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        )
        name:         Mapped[str] = mapped_column(String(160), nullable=False)
        category:     Mapped[str] = mapped_column(String(32), nullable=False)
        source_url:   Mapped[str | None] = mapped_column(Text, nullable=True)
        embedding:    Mapped[list[float]] = mapped_column(JSON, nullable=False)
        created_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )

    # ---- Chat (M8) ---------------------------------------------------
    #
    # Phase B persistence for the worship/music chatbot. In Phase A both
    # tables are unused — the chat service uses an in-memory registry +
    # browser localStorage (see backend/app/chat/sessions.py and the
    # frontend useChatSession hook). When Phase B lights up, the
    # ChatService grows a ``_persist_to_db`` shim that writes here.

    class ChatConversation(Base):
        """One conversation thread (sidebar entry) per row.

        ``user_id`` is nullable so Phase A guest sessions can still be
        backfilled when a guest signs up — the migration script reassigns
        ``user_id`` after sign-up.
        """
        __tablename__ = "chat_conversations"
        id:           Mapped[str] = mapped_column(String(32), primary_key=True)
        user_id:      Mapped[str | None] = mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
        )
        title:        Mapped[str | None] = mapped_column(String(200), nullable=True)
        # Job context snapshot frozen on the conversation when the user
        # opened the widget on a Job page (key/BPM/chord_summary etc).
        job_context:  Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
        created_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
        updated_at:   Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
            nullable=False,
        )
        messages:     Mapped[list["ChatMessage"]] = relationship(
            back_populates="conversation",
            cascade="all, delete-orphan",
            order_by="ChatMessage.created_at",
        )

    class ChatMessage(Base):
        """Individual chat turn. ``content_json`` carries structured data
        the bubble UI needs: attachment ids, parsed confidence, ai-trans
        blocks, executed tool invocations.
        """
        __tablename__ = "chat_messages"
        id:              Mapped[str] = mapped_column(String(32), primary_key=True)
        conversation_id: Mapped[str] = mapped_column(
            ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=False, index=True,
        )
        # role: "user" | "assistant" | "system" | "tool"
        role:            Mapped[str] = mapped_column(String(16), nullable=False)
        content_text:    Mapped[str] = mapped_column(Text, nullable=False, default="")
        content_json:    Mapped[dict[str, Any]] = mapped_column(
            JSON, default=dict, nullable=False,
        )
        # Optional parsed confidence (0..1) extracted from <confidence>
        # tokens so the UI doesn't have to re-parse every render.
        confidence:      Mapped[float | None] = mapped_column(Float, nullable=True)
        created_at:      Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
        conversation:    Mapped["ChatConversation"] = relationship(
            back_populates="messages",
        )

else:                                # noqa: SIM108
    class Base:                      # type: ignore[no-redef]
        """Placeholder so module-level imports don't crash without SQLAlchemy."""
