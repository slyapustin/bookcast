from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..deps import db_session, templates
from ..models import Book, BookStatus, Chapter, ChapterStatus, JobKind
from ..queue import enqueue
from ..tts.router import all_supported_languages, voices_for

router = APIRouter()


@router.get("/book/{book_id}")
async def book_detail(
    book_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
):
    book = await _get_book(session, book_id)
    chapters = (
        await session.execute(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.idx))
    ).scalars().all()
    voices_by_lang = {}
    for lang in all_supported_languages():
        try:
            voices_by_lang[lang] = voices_for(lang)
        except Exception:
            voices_by_lang[lang] = []
    feed_url = f"{settings.base_url.rstrip('/')}/feed/{book.feed_token}"
    return templates.TemplateResponse(
        request,
        "book.html",
        {
            "book": book,
            "chapters": chapters,
            "voices_by_lang": voices_by_lang,
            "feed_url": feed_url,
            "supported_languages": all_supported_languages(),
            "done_count": sum(1 for c in chapters if c.status in {ChapterStatus.done, ChapterStatus.skipped}),
        },
    )


@router.post("/book/{book_id}/metadata")
async def update_book_metadata(
    book_id: int,
    title: str = Form(...),
    author: str = Form(""),
    session: AsyncSession = Depends(db_session),
):
    book = await _get_book(session, book_id)
    clean_title = title.strip()
    clean_author = author.strip()
    if not clean_title:
        raise HTTPException(400, "Title is required")
    book.title = clean_title[:500]
    book.author = clean_author[:500] or None
    return RedirectResponse(f"/book/{book.id}", status_code=303)


@router.post("/book/{book_id}/render")
async def render_book(
    book_id: int,
    request: Request,
    language: str = Form(...),
    voice: str = Form(...),
    session: AsyncSession = Depends(db_session),
):
    book = await _get_book(session, book_id)
    if book.status not in {BookStatus.ready_to_render, BookStatus.done, BookStatus.failed}:
        raise HTTPException(409, "Book not ready to render yet")
    if language not in all_supported_languages():
        raise HTTPException(400, f"Unsupported language: {language}")
    valid_voices = {v.id for v in voices_for(language)}
    if voice not in valid_voices:
        raise HTTPException(
            400, f"Voice '{voice}' is not available for language '{language}'"
        )
    book.language = language[:8]
    book.voice = voice[:64]
    book.status = BookStatus.rendering
    chapters = (
        await session.execute(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.idx))
    ).scalars().all()
    for ch in chapters:
        if ch.status == ChapterStatus.skipped:
            continue
        if ch.status != ChapterStatus.done:
            ch.status = ChapterStatus.pending
            ch.error = None
            await enqueue(session, JobKind.tts_chapter, ch.id)
    return RedirectResponse(f"/book/{book.id}", status_code=303)


@router.post("/book/{book_id}/chapter/{chapter_id}/skip")
async def toggle_skip_chapter(
    book_id: int,
    chapter_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
):
    book = await _get_book(session, book_id)
    chapter = (
        await session.execute(
            select(Chapter).where(Chapter.id == chapter_id, Chapter.book_id == book.id)
        )
    ).scalar_one_or_none()
    if chapter is None:
        raise HTTPException(404)
    chapter.status = (
        ChapterStatus.pending if chapter.status == ChapterStatus.skipped else ChapterStatus.skipped
    )
    # HTMX request → return the refreshed chapter-list fragment so the page
    # doesn't full-reload. Anything else → redirect (graceful degradation).
    if request.headers.get("hx-request") == "true":
        await session.commit()
        return await book_progress(book.id, request, session)
    return RedirectResponse(f"/book/{book.id}", status_code=303)


@router.post("/book/{book_id}/delete")
async def delete_book(
    book_id: int,
    session: AsyncSession = Depends(db_session),
):
    book = await _get_book(session, book_id)
    # Best-effort filesystem cleanup
    for p in (book.source_path, book.cover_path):
        if p:
            Path(p).unlink(missing_ok=True)
    chapters_dir = settings.chapters_dir / str(book.id)
    if chapters_dir.exists():
        for f in chapters_dir.glob("*"):
            f.unlink(missing_ok=True)
        chapters_dir.rmdir()
    await session.delete(book)
    return RedirectResponse("/", status_code=303)


@router.get("/book/{book_id}/progress")
async def book_progress(
    book_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
):
    """HTMX poll target — returns the chapter table fragment with progress."""
    from ..models import Chunk, ChunkStatus

    book = await _get_book(session, book_id)
    chapters = (
        await session.execute(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.idx))
    ).scalars().all()

    # Per-chapter chunk progress (only fetched for chapters currently rendering).
    chunk_stats: dict[int, tuple[int, int]] = {}
    rendering_ids = [c.id for c in chapters if c.status == ChapterStatus.rendering]
    if rendering_ids:
        rows = (
            await session.execute(
                select(Chunk.chapter_id, Chunk.status).where(Chunk.chapter_id.in_(rendering_ids))
            )
        ).all()
        for chapter_id, status in rows:
            done, total = chunk_stats.get(chapter_id, (0, 0))
            chunk_stats[chapter_id] = (
                done + (1 if status == ChunkStatus.done else 0),
                total + 1,
            )

    done_count = sum(1 for c in chapters if c.status in {ChapterStatus.done, ChapterStatus.skipped})
    rendering_count = len(rendering_ids)
    overall_pct = round(100 * done_count / max(1, len(chapters)))

    return templates.TemplateResponse(
        request,
        "_book_progress.html",
        {
            "book": book,
            "chapters": chapters,
            "chunk_stats": chunk_stats,
            "done_count": done_count,
            "rendering_count": rendering_count,
            "overall_pct": overall_pct,
        },
    )


@router.get("/cover/{token}.jpg")
async def cover(
    token: str,
    session: AsyncSession = Depends(db_session),
):
    book = (
        await session.execute(select(Book).where(Book.feed_token == token))
    ).scalar_one_or_none()
    if book is None or not book.cover_path or not Path(book.cover_path).exists():
        raise HTTPException(404)
    return FileResponse(book.cover_path, media_type="image/jpeg")


async def _get_book(session: AsyncSession, book_id: int) -> Book:
    book = (
        await session.execute(select(Book).where(Book.id == book_id))
    ).scalar_one_or_none()
    if book is None:
        raise HTTPException(404)
    return book
