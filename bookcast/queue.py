from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Job, JobKind, JobState


async def enqueue(session: AsyncSession, kind: JobKind, ref_id: int) -> Job:
    job = Job(kind=kind, ref_id=ref_id, state=JobState.pending)
    session.add(job)
    await session.flush()
    return job


async def claim_one(session: AsyncSession) -> Job | None:
    """Pop one pending job and mark it running.

    Priority ordering: assemble_chapter > tts_chapter > parse_book. This makes
    finished chapters appear in the feed as soon as their chunks are rendered,
    instead of waiting for every chapter's TTS to finish first.
    """
    kind_priority = case(
        {
            JobKind.assemble_chapter: 0,
            JobKind.tts_chapter: 1,
            JobKind.parse_book: 2,
        },
        value=Job.kind,
        else_=3,
    )
    candidate = (
        await session.execute(
            select(Job)
            .where(Job.state == JobState.pending)
            .order_by(kind_priority.asc(), Job.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if candidate is None:
        return None
    result = await session.execute(
        update(Job)
        .where(Job.id == candidate.id, Job.state == JobState.pending)
        .values(state=JobState.running, started_at=datetime.now(UTC))
    )
    if result.rowcount == 0:
        # Lost the race; caller will retry.
        return None
    await session.refresh(candidate)
    return candidate


async def mark_done(session: AsyncSession, job_id: int) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state=JobState.done, finished_at=datetime.now(UTC), progress=1.0)
    )


async def mark_failed(session: AsyncSession, job_id: int, error: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(state=JobState.failed, finished_at=datetime.now(UTC), error=error[:2000])
    )


async def update_progress(session: AsyncSession, job_id: int, progress: float) -> None:
    await session.execute(
        update(Job).where(Job.id == job_id).values(progress=max(0.0, min(1.0, progress)))
    )
