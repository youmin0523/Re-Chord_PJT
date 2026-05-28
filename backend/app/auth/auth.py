"""Auth backend (Phase B).

Two strategies, picked by ``AUTH_PROVIDER`` env var. Phase A keeps
this entire module behind ``get_current_user()`` which silently returns
``GuestUser`` when no provider is configured, so endpoint signatures
stay identical between phases.

JWKS is cached in-memory with a 1-hour TTL — the keys rotate
infrequently and we don't want every request hitting the provider's
``/.well-known/`` URL.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, HTTPException, status


PROVIDER = os.environ.get("AUTH_PROVIDER", "").strip().lower()
CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "").strip()
CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL", "").strip()
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "").strip()


@dataclass
class User:
    id: str
    email: str | None = None
    name: str | None = None
    is_guest: bool = False


@dataclass
class GuestUser(User):
    is_guest: bool = True


_JWKS_CACHE: dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL = 3600.0


def _fetch_jwks(url: str) -> dict[str, Any]:
    """Lazy + cached JWKS fetch — used by Clerk verification."""
    now = time.time()
    if _JWKS_CACHE["keys"] and (now - _JWKS_CACHE["fetched_at"] < _JWKS_TTL):
        return _JWKS_CACHE["keys"]
    import json
    import urllib.request
    with urllib.request.urlopen(url, timeout=5.0) as resp:
        keys = json.loads(resp.read().decode("utf-8"))
    _JWKS_CACHE["keys"] = keys
    _JWKS_CACHE["fetched_at"] = now
    return keys


def _decode_clerk(token: str) -> User:
    try:
        from jose import jwt  # type: ignore
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="python-jose not installed; run `uv pip install python-jose`",
        ) from e
    if not CLERK_JWKS_URL or not CLERK_ISSUER:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CLERK_JWKS_URL / CLERK_ISSUER not configured",
        )
    jwks = _fetch_jwks(CLERK_JWKS_URL)
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not key:
            raise HTTPException(status_code=401, detail="Unknown signing key")
        claims = jwt.decode(
            token, key, algorithms=[unverified_header.get("alg", "RS256")],
            issuer=CLERK_ISSUER, options={"verify_aud": False},
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}") from e
    return User(
        id=str(claims.get("sub") or claims.get("user_id") or ""),
        email=claims.get("email"),
        name=claims.get("name") or claims.get("nickname"),
    )


def _decode_supabase(token: str) -> User:
    try:
        from jose import jwt  # type: ignore
    except ImportError as e:
        raise HTTPException(status_code=503, detail="python-jose not installed") from e
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(status_code=503, detail="SUPABASE_JWT_SECRET not set")
    try:
        claims = jwt.decode(token, SUPABASE_JWT_SECRET,
                             algorithms=["HS256"], options={"verify_aud": False})
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}") from e
    return User(
        id=str(claims.get("sub") or ""),
        email=claims.get("email"),
        name=(claims.get("user_metadata") or {}).get("full_name"),
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> User:
    """Return the user resolved from the bearer token, or ``GuestUser`` in Phase A."""
    if not PROVIDER:
        return GuestUser(id="guest", name="guest")
    if not authorization or not authorization.lower().startswith("bearer "):
        # Endpoints can decide whether to allow unauthenticated. Return guest
        # so the route handler can check ``user.is_guest`` and 401 if needed.
        return GuestUser(id="guest", name="guest")
    token = authorization.split(" ", 1)[1].strip()
    if PROVIDER == "clerk":
        return _decode_clerk(token)
    if PROVIDER == "supabase":
        return _decode_supabase(token)
    raise HTTPException(
        status_code=500, detail=f"Unknown AUTH_PROVIDER: {PROVIDER!r}",
    )


def auth_dependency():
    """FastAPI Depends shorthand: ``user: User = Depends(auth_dependency())``."""
    return Depends(get_current_user)
