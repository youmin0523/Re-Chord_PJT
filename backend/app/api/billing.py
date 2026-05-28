"""Billing webhook endpoints — 토스페이먼츠 (Korea) + Stripe (global).

Phase B SaaS. Both endpoints expect HMAC-signed webhook bodies. We
verify signature, persist the subscription state in the DB, and return
200. Failure to verify → 401.

Phase A: the routes return 200 but no-op (we don't have a DB to write
to yet). Existing API clients can wire to this URL during pre-launch
testing without disrupting development.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request


router = APIRouter(prefix="/billing", tags=["billing"])


TOSS_SECRET = os.environ.get("TOSS_WEBHOOK_SECRET", "")
STRIPE_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def _verify_hmac(payload: bytes, secret: str, header_value: str | None,
                 algorithm: str = "sha256") -> bool:
    if not secret or not header_value:
        return False
    digest = hmac.new(secret.encode("utf-8"), payload, algorithm).hexdigest()
    return hmac.compare_digest(digest, header_value.strip())


@router.post("/toss")
async def toss_webhook(
    request: Request,
    x_toss_signature: str | None = Header(default=None),
):
    """토스페이먼츠 webhook. Verifies signature, updates subscription state."""
    body = await request.body()
    if TOSS_SECRET and not _verify_hmac(body, TOSS_SECRET, x_toss_signature):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        event: dict[str, Any] = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    # Phase A: log + no-op. Phase B: dispatch to subscription handler.
    event_type = event.get("eventType") or event.get("type") or "unknown"
    return {"ok": True, "event_type": event_type, "phase": "A — no-op"}


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None),
):
    """Stripe webhook. Phase A: parse + log. Phase B: subscription state."""
    body = await request.body()
    if STRIPE_SECRET and not _verify_stripe_sig(body, STRIPE_SECRET, stripe_signature):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        event = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    return {"ok": True, "event_type": event.get("type"), "phase": "A — no-op"}


def _verify_stripe_sig(payload: bytes, secret: str, header_value: str | None) -> bool:
    """Stripe-Signature header is ``t=…,v1=…``. Verify v1 HMAC-SHA256."""
    if not secret or not header_value:
        return False
    parts = dict(p.split("=", 1) for p in header_value.split(",") if "=" in p)
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        return False
    signed = f"{timestamp}.{payload.decode('utf-8', errors='ignore')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
