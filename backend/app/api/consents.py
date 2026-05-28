"""User-consent API (PIPA / GDPR audit trail).

Phase B feature — depends on the Supabase/Clerk auth dependency and the
``user_consents`` table (Alembic revision b3c0d5e1f9a2). Guest users
hit 401 here because consent only makes sense once we know who's
agreeing.

Routes:
    POST   /consents            grant or update a single consent
    GET    /consents/me         list this user's current consents
    DELETE /consents/{type}     revoke a consent (sets revoked_at)

Allowed ``consent_type`` values are gated by ``CONSENT_TYPES`` so a
typo in the frontend (or a malicious client) can't sneak a free-form
string into the audit trail.

See docs/legal/consent_ui_spec.md for the spec.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..auth.auth import User, get_current_user


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
                         description="Policy version (e.g. '2026-05-28-v0.1')")
    granted: bool = Field(default=True, description="False = revoke")


class ConsentRecord(BaseModel):
    consent_type: str
    version: str
    granted: bool
    granted_at: datetime
    revoked_at: datetime | None


# ── In-memory store fallback ──────────────────────────────────────
#
# Phase A doesn't have a database, but the frontend will still want to
# call these endpoints during dev. We keep a tiny in-process dict
# keyed by user_id so the API contract is identical.

_MEM_CONSENTS: dict[tuple[str, str, str], dict] = {}


def _require_authenticated(user: User) -> User:
    if getattr(user, "is_guest", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for consent management",
        )
    return user


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

    key = (user.id, body.consent_type, body.version)
    now = datetime.now(timezone.utc)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

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


@router.get("/me", response_model=list[ConsentRecord])
async def list_my_consents(
    user: User = Depends(get_current_user),
) -> list[ConsentRecord]:
    """Return every consent row for the current user (newest first)."""
    _require_authenticated(user)
    rows = [
        rec for (uid, _t, _v), rec in _MEM_CONSENTS.items() if uid == user.id
    ]
    rows.sort(key=lambda r: r["granted_at"], reverse=True)
    return [
        ConsentRecord(**{k: v for k, v in r.items() if k in ConsentRecord.model_fields})
        for r in rows
    ]


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

    now = datetime.now(timezone.utc)
    revoked = 0
    for (uid, ctype, _v), rec in _MEM_CONSENTS.items():
        if uid == user.id and ctype == consent_type and rec.get("revoked_at") is None:
            rec["revoked_at"] = now
            revoked += 1

    return {"consent_type": consent_type, "revoked": revoked}
