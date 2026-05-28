"""Database layer (Phase B SaaS).

Phase A runs entirely on in-memory dicts + JSON files (the current
``registry`` in core/jobs.py and the JSON stores in api/setlists.py /
api/notes.py). When the platform moves to multi-tenant SaaS, this
package becomes the persistence layer: PostgreSQL via SQLAlchemy 2.x
async + Alembic migrations.

Importing this module DOES NOT require a database connection — the
engine is lazy-loaded on first ``get_session()`` call. Set
``DATABASE_URL`` env var (e.g. ``postgresql+asyncpg://user:pw@host/db``)
to enable; absence keeps everything strictly file-based.

Layout:
    models.py        — SQLAlchemy table definitions (users, jobs, setlists, notes)
    session.py       — async engine + session factory
    repository.py    — query helpers (jobs.get_or_create, ...)
    migrations/      — Alembic auto-generated migrations (env.py + versions/)
"""

from .session import get_session, get_engine

__all__ = ["get_session", "get_engine"]
