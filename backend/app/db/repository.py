"""Repository pattern — query helpers used by the API layer.

Each function takes an ``AsyncSession`` and returns/mutates ORM rows.
Keeping the SQL inside this module means the API endpoints stay free
of SQLAlchemy imports.
"""

from __future__ import annotations

from typing import Any


async def get_job(session, job_id: str):
    from sqlalchemy import select
    from .models import Job
    result = await session.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def list_jobs(session, *, user_id: str | None = None, limit: int = 50):
    from sqlalchemy import select
    from .models import Job
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(Job.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalars().all()


async def upsert_job(session, *, id: str, user_id: str | None, **fields) -> Any:
    """Insert or update a job row by id."""
    from .models import Job
    existing = await get_job(session, id)
    if existing is None:
        job = Job(id=id, user_id=user_id, **fields)
        session.add(job)
    else:
        for k, v in fields.items():
            setattr(existing, k, v)
        job = existing
    await session.commit()
    return job


async def get_setlists(session, *, user_id: str | None = None):
    from sqlalchemy import select
    from .models import Setlist
    stmt = select(Setlist).order_by(Setlist.created_at.desc())
    if user_id:
        stmt = stmt.where(Setlist.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalars().all()


async def add_note(session, *, id: str, job_id: str, text: str,
                   kind: str = "note",
                   start_sec: float | None = None,
                   end_sec: float | None = None):
    from .models import Note
    note = Note(id=id, job_id=job_id, text=text, kind=kind,
                start_sec=start_sec, end_sec=end_sec)
    session.add(note)
    await session.commit()
    return note
