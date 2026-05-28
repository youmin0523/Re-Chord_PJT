"""Async SQLAlchemy engine + session factory (Phase B SaaS).

Lazy: the engine is created only when ``get_engine()`` or ``get_session()``
is first called, and only when ``DATABASE_URL`` is set. Phase A code
keeps using the in-memory ``core.jobs.registry`` and never touches this
module, so absence of asyncpg / SQLAlchemy at install time is harmless.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator


_engine = None
_session_factory = None


def database_url() -> str | None:
    """Resolve the SQLAlchemy URL. ``None`` means "no database configured"."""
    return os.environ.get("DATABASE_URL") or None


def get_engine():
    """Return the lazily-built async engine, or ``None`` when unconfigured."""
    global _engine
    if _engine is not None:
        return _engine
    url = database_url()
    if not url:
        return None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError as e:
        raise RuntimeError(
            "SQLAlchemy is not installed. Run: uv pip install 'sqlalchemy[asyncio]>=2.0' asyncpg"
        ) from e
    _engine = create_async_engine(url, pool_pre_ping=True, echo=False)
    return _engine


def get_session_factory():
    """Return the async session factory bound to the engine."""
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    engine = get_engine()
    if engine is None:
        return None
    from sqlalchemy.ext.asyncio import async_sessionmaker
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator:
    """Async context manager that yields an AsyncSession (or raises if unconfigured)."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL not set — database layer is disabled in Phase A")
    async with factory() as session:
        yield session
