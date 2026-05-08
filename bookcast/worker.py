from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, update

from .db import session_scope
from .models import Job, JobKind, JobState
from .queue import claim_one, mark_done, mark_failed
from .tasks import assemble_chapter, parse_book, tts_chapter

log = logging.getLogger("bookcast.worker")

POLL_INTERVAL_S = 0.5
IDLE_INTERVAL_S = 1.5


async def run() -> None:
    stop = asyncio.Event()

    def _signal(*_a):
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal)

    # Reclaim only *stale* running jobs — ones that haven't progressed in a
    # long time. With multiple worker processes, freshly running jobs may
    # belong to a sibling worker, so a hard cutoff is required.
    stale_after = datetime.now(UTC) - timedelta(minutes=10)
    async with session_scope() as session:
        result = await session.execute(
            update(Job)
            .where(
                Job.state == JobState.running,
                or_(Job.started_at.is_(None), Job.started_at < stale_after),
            )
            .values(state=JobState.pending, started_at=None)
        )
        if result.rowcount:
            log.info("reclaimed %s stale running job(s)", result.rowcount)

    log.info("worker started")
    while not stop.is_set():
        job = await _claim()
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=IDLE_INTERVAL_S)
            except TimeoutError:
                pass
            continue
        log.info("processing job %s kind=%s ref=%s", job.id, job.kind.value, job.ref_id)
        try:
            await _dispatch(job.kind, job.ref_id, job.id)
            async with session_scope() as session:
                await mark_done(session, job.id)
            log.info("job %s done", job.id)
        except Exception as e:
            log.exception("job %s failed", job.id)
            async with session_scope() as session:
                await mark_failed(session, job.id, str(e))
    log.info("worker stopped")


async def _claim():
    async with session_scope() as session:
        return await claim_one(session)


async def _dispatch(kind: JobKind, ref_id: int, job_id: int) -> None:
    if kind == JobKind.parse_book:
        await parse_book(ref_id, job_id)
    elif kind == JobKind.tts_chapter:
        await tts_chapter(ref_id, job_id)
    elif kind == JobKind.assemble_chapter:
        await assemble_chapter(ref_id, job_id)
    else:
        raise ValueError(f"unknown job kind {kind}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
