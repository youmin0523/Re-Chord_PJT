"""User-consent API (PIPA / GDPR audit trail).

Phase B feature — depends on the Supabase/Clerk auth dependency. Guest
users hit 401 here because consent only makes sense once we know who's
agreeing.

Routes:
    POST   /consents            grant or update a single consent
    GET    /consents/me         list this user's current consents
    DELETE /consents/{type}     revoke a consent (sets revoked_at)

Persistence:
    * DATABASE_URL set     → SQLAlchemy AsyncSession + ``user_consents``
                              table (Alembic revision b3c0d5e1f9a2).
                              Survives restarts → PIPA audit trail.
    * DATABASE_URL unset   → in-memory dict fallback (Phase A dev only).
                              Lost on restart; warned at first write.

Allowed ``consent_type`` values are gated by ``CONSENT_TYPES`` so a typo
in the frontend (or a malicious client) can't sneak a free-form string
into the audit trail.

See docs/legal/consent_ui_spec.md for the spec.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..auth.auth import User, get_current_user
from ..db.session import database_url, get_session


log = logging.getLogger(__name__)

router = APIRouter(prefix="/consents", tags=["consents"])


# Whitelisted consent identifiers — must match the frontend's
# SignupConsent component IDs. Adding a new one requires:
#   1. add the literal here
#   2. update docs/legal/consent_ui_spec.md
#   3. publish a new policy version string
CONSENT_TYPES = (
    "tos",                # 이용약관
    "privacy",            # 개인정보 수집·이용 동의
    "intl_transfer",      # 개인정보 국외이전 동의
    "age_14",             # 만 14세 이상 확인
    "copyright_self",     # 저작권 책임 자가 진술
    "marketing",          # 선택 — 마케팅 정보 수신
)
ConsentType = Literal[
    "tos", "privacy", "intl_transfer", "age_14", "copyright_self", "marketing",
]


# ── Schemas ───────────────────────────────────────────────────────


class ConsentGrant(BaseModel):
    consent_type: ConsentType = Field(description="Whitelisted consent identifier")
    version: str = Field(min_length=1, max_length=40,
                         description="Policy version (e.g. '2026-05-29-v1.0')")
    granted: bool = Field(default=True, description="False = revoke")


class ConsentRecord(BaseModel):
    consent_type: str
    version: str
    granted: bool
    granted_at: datetime
    revoked_at: datetime | None


# ── In-memory store fallback ──────────────────────────────────────
#
# Used when DATABASE_URL is not set (Phase A). Phase B writes to the
# ``user_consents`` table via SQLAlchemy; rows survive restarts.

_MEM_CONSENTS: dict[tuple[str, str, str], dict] = {}
_FALLBACK_WARNED = False


def _persistent() -> bool:
    """True when we should hit the DB; False → in-memory fallback."""
    return bool(database_url())


def _warn_fallback_once() -> None:
    global _FALLBACK_WARNED
    if not _FALLBACK_WARNED:
        log.warning(
            "consents API running in IN-MEMORY mode (DATABASE_URL unset). "
            "Consent records will be lost on restart. "
            "Configure DATABASE_URL and run alembic upgrade head for PIPA persistence.",
        )
        _FALLBACK_WARNED = True


def _require_authenticated(user: User) -> User:
    if getattr(user, "is_guest", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for consent management",
        )
    return user


# ── DB helpers ────────────────────────────────────────────────────


async def _ensure_user_row(session, user: User) -> None:
    """Insert a stub users row if it doesn't exist.

    UserConsent FK ON DELETE CASCADE references users.id. New first-time
    signups won't have a users row yet (auth provider verifies the JWT
    but never writes through to our DB), so we upsert here.
    """
    from sqlalchemy import select
    from ..db.models import User as DbUser

    existing = await session.scalar(
        select(DbUser).where(DbUser.id == user.id)
    )
    if existing is None:
        session.add(DbUser(
            id=user.id,
            email=user.email,
            display_name=user.name,
        ))
        await session.flush()


async def _db_grant(user: User, body: ConsentGrant, ip: str | None, ua: str | None) -> ConsentRecord:
    from sqlalchemy import select
    from ..db.models import UserConsent

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        await _ensure_user_row(session, user)
        existing = await session.scalar(
            select(UserConsent).where(
                UserConsent.user_id == user.id,
                UserConsent.consent_type == body.consent_type,
                UserConsent.version == body.version,
            )
        )
        if existing is None:
            row = UserConsent(
                user_id=user.id,
                consent_type=body.consent_type,
                version=body.version,
                granted=body.granted,
                granted_at=now,
                revoked_at=None if body.granted else now,
                ip_address=ip,
                user_agent=ua,
            )
            session.add(row)
        else:
            row = existing
            if not body.granted and row.revoked_at is None:
                row.revoked_at = now
            elif body.granted and row.revoked_at is not None:
                row.revoked_at = None
                row.granted_at = now
        await session.commit()
        # Re-read to get any DB-managed defaults (granted_at server default).
        await session.refresh(row)
        return ConsentRecord(
            consent_type=row.consent_type,
            version=row.version,
            granted=row.granted,
            granted_at=row.granted_at,
            revoked_at=row.revoked_at,
        )


async def _db_list(user: User) -> list[ConsentRecord]:
    from sqlalchemy import select
    from ..db.models import UserConsent
    async with get_session() as session:
        rows = (await session.scalars(
            select(UserConsent)
            .where(UserConsent.user_id == user.id)
            .order_by(UserConsent.granted_at.desc())
        )).all()
        return [
            ConsentRecord(
                consent_type=r.consent_type, version=r.version,
                granted=r.granted, granted_at=r.granted_at,
                revoked_at=r.revoked_at,
            ) for r in rows
        ]


async def _db_revoke(user: User, consent_type: str) -> int:
    from sqlalchemy import select, update
    from ..db.models import UserConsent
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        # Count active grants first so we can return how many we revoked.
        active = (await session.scalars(
            select(UserConsent.id).where(
                UserConsent.user_id == user.id,
                UserConsent.consent_type == consent_type,
                UserConsent.revoked_at.is_(None),
            )
        )).all()
        if not active:
            return 0
        await session.execute(
            update(UserConsent)
            .where(UserConsent.id.in_(active))
            .values(revoked_at=now)
        )
        await session.commit()
        return len(active)


# ── In-memory fallback ────────────────────────────────────────────


def _mem_grant(user: User, body: ConsentGrant, ip: str | None, ua: str | None) -> ConsentRecord:
    _warn_fallback_once()
    key = (user.id, body.consent_type, body.version)
    now = datetime.now(timezone.utc)
    existing = _MEM_CONSENTS.get(key)
    if existing:
        if not body.granted and existing.get("revoked_at") is None:
            existing["revoked_at"] = now
        elif body.granted and existing.get("revoked_at") is not None:
            existing["revoked_at"] = None
            existing["granted_at"] = now
    else:
        _MEM_CONSENTS[key] = {
            "consent_type": body.consent_type,
            "version": body.version,
            "granted": body.granted,
            "granted_at": now,
            "revoked_at": None if body.granted else now,
            "ip_address": ip,
            "user_agent": ua,
            "user_id": user.id,
        }
    rec = _MEM_CONSENTS[key]
    return ConsentRecord(**{k: v for k, v in rec.items() if k in ConsentRecord.model_fields})


def _mem_list(user: User) -> list[ConsentRecord]:
    rows = [
        rec for (uid, _t, _v), rec in _MEM_CONSENTS.items() if uid == user.id
    ]
    rows.sort(key=lambda r: r["granted_at"], reverse=True)
    return [
        ConsentRecord(**{k: v for k, v in r.items() if k in ConsentRecord.model_fields})
        for r in rows
    ]


def _mem_revoke(user: User, consent_type: str) -> int:
    _warn_fallback_once()
    now = datetime.now(timezone.utc)
    revoked = 0
    for (uid, ctype, _v), rec in _MEM_CONSENTS.items():
        if uid == user.id and ctype == consent_type and rec.get("revoked_at") is None:
            rec["revoked_at"] = now
            revoked += 1
    return revoked


# ── Routes ────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_200_OK, response_model=ConsentRecord)
async def grant_consent(
    body: ConsentGrant,
    request: Request,
    user: User = Depends(get_current_user),
) -> ConsentRecord:
    """Record or update a single consent row.

    Idempotent on ``(user_id, consent_type, version)`` — calling twice
    with ``granted=true`` is a no-op; calling with ``granted=false``
    revokes (sets ``revoked_at``).
    """
    _require_authenticated(user)
    if body.consent_type not in CONSENT_TYPES:
        # Defensive — pydantic Literal should catch this already.
        raise HTTPException(status_code=422, detail="Unknown consent_type")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    if _persistent():
        return await _db_grant(user, body, ip, ua)
    return _mem_grant(user, body, ip, ua)


@router.get("/me", response_model=list[ConsentRecord])
async def list_my_consents(
    user: User = Depends(get_current_user),
) -> list[ConsentRecord]:
    """Return every consent row for the current user (newest first)."""
    _require_authenticated(user)
    if _persistent():
        return await _db_list(user)
    return _mem_list(user)


@router.delete("/{consent_type}", status_code=status.HTTP_200_OK)
async def revoke_consent(
    consent_type: ConsentType,
    user: User = Depends(get_current_user),
) -> dict:
    """Revoke ALL active grants of the given consent_type for this user.

    Sets ``revoked_at`` on each matching row. Returns the number of rows
    affected so the frontend can confirm.
    """
    _require_authenticated(user)
    if consent_type not in CONSENT_TYPES:
        raise HTTPException(status_code=422, detail="Unknown consent_type")

    if _persistent():
        revoked = await _db_revoke(user, consent_type)
    else:
        revoked = _mem_revoke(user, consent_type)
    return {"consent_type": consent_type, "revoked": revoked}
