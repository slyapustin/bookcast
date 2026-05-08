from __future__ import annotations

import hashlib
from datetime import UTC
from email.utils import format_datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import db_session
from ..models import Book, Chapter, ChapterStatus
from ..rss import build_book_feed

router = APIRouter()


@router.get("/feed/{token}")
async def book_feed(
    token: str,
    request: Request,
    session: AsyncSession = Depends(db_session),
):
    book = (
        await session.execute(select(Book).where(Book.feed_token == token))
    ).scalar_one_or_none()
    if book is None:
        raise HTTPException(404)
    chapters = (
        await session.execute(
            select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.idx)
        )
    ).scalars().all()

    # ETag/Last-Modified driven by the most recent done-chapter timestamp +
    # the count of done chapters. Apple Podcasts uses these to decide whether
    # to re-fetch the feed.
    done = [c for c in chapters if c.status == ChapterStatus.done]
    last_mod = max((c.created_at for c in done), default=book.created_at)
    if last_mod.tzinfo is None:
        last_mod = last_mod.replace(tzinfo=UTC)
    etag_src = f"{book.id}:{book.feed_token}:{len(done)}:{last_mod.isoformat()}"
    etag = '"' + hashlib.sha256(etag_src.encode()).hexdigest()[:32] + '"'

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    xml = build_book_feed(book, chapters)
    return Response(
        xml,
        media_type="application/rss+xml; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=60",
            "ETag": etag,
            "Last-Modified": format_datetime(last_mod, usegmt=True),
        },
    )


@router.get("/audio/{chapter_id}.mp3")
async def chapter_audio(
    chapter_id: int,
    t: str = Query(...),
    session: AsyncSession = Depends(db_session),
):
    chapter = (
        await session.execute(select(Chapter).where(Chapter.id == chapter_id))
    ).scalar_one_or_none()
    if chapter is None or chapter.mp3_path is None:
        raise HTTPException(404)
    book = (
        await session.execute(select(Book).where(Book.id == chapter.book_id))
    ).scalar_one_or_none()
    if book is None or book.feed_token != t:
        raise HTTPException(404)
    if not Path(chapter.mp3_path).exists():
        raise HTTPException(404)
    return FileResponse(chapter.mp3_path, media_type="audio/mpeg")
