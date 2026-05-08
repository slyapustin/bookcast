from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import audio as audio_mod
from . import parsers
from .config import settings
from .cover import render_cover
from .db import session_scope
from .models import Book, BookStatus, Chapter, ChapterStatus, Chunk, ChunkStatus, JobKind
from .queue import enqueue, update_progress
from .tts.router import get_engine

log = logging.getLogger(__name__)


async def parse_book(book_id: int, job_id: int) -> None:
    """Parse the source file, populate chapters, render cover, mark ready_to_render."""
    async with session_scope() as session:
        book = await _get_book(session, book_id)
        book.status = BookStatus.parsing
        await session.flush()

    parsed = await asyncio.to_thread(parsers.parse, Path(_book_source_path(book_id)))

    async with session_scope() as session:
        book = await _get_book(session, book_id)
        book.title = parsed.title or book.title
        book.author = parsed.author
        if parsed.language:
            # Normalize "en-US" → "en" so the value matches the supported set.
            book.language = parsed.language.lower().split("-", 1)[0][:8]

        cover_path = settings.covers_dir / f"{book.id}.jpg"
        await asyncio.to_thread(
            render_cover,
            raw=parsed.cover_bytes,
            title=book.title,
            author=book.author,
            out_path=cover_path,
        )
        book.cover_path = str(cover_path)

        # Insert chapters
        existing = (
            await session.execute(select(Chapter).where(Chapter.book_id == book.id))
        ).scalars().all()
        for ch in existing:
            await session.delete(ch)
        for idx, pc in enumerate(parsed.chapters, start=1):
            session.add(
                Chapter(
                    book_id=book.id,
                    idx=idx,
                    title=pc.title,
                    text=pc.text,
                    status=ChapterStatus.pending,
                )
            )

        book.status = BookStatus.ready_to_render
        book.error = None
        await session.flush()
        await update_progress(session, job_id, 1.0)


async def tts_chapter(chapter_id: int, job_id: int) -> None:
    """Render TTS for one chapter, with chunk-level resume."""
    async with session_scope() as session:
        chapter = (await session.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one()
        if chapter.status == ChapterStatus.skipped:
            log.info("chapter %s is skipped — bailing", chapter_id)
            return
        if chapter.status == ChapterStatus.done:
            log.info("chapter %s is already done — bailing", chapter_id)
            return
        book = await _get_book(session, chapter.book_id)
        chapter.status = ChapterStatus.rendering
        chapter.error = None
        # Ensure chunks exist
        existing_chunks = (
            await session.execute(select(Chunk).where(Chunk.chapter_id == chapter.id))
        ).scalars().all()
        if not existing_chunks:
            for idx, text in enumerate(audio_mod.split_for_tts(chapter.text), start=1):
                session.add(
                    Chunk(
                        chapter_id=chapter.id,
                        idx=idx,
                        text=text,
                        status=ChunkStatus.pending,
                    )
                )
        await session.flush()
        chunks = (
            await session.execute(
                select(Chunk).where(Chunk.chapter_id == chapter.id).order_by(Chunk.idx)
            )
        ).scalars().all()
        chapter_lang = book.language or "en"
        chapter_voice = book.voice or _default_voice_for(chapter_lang)
        chunk_dir = settings.chunks_dir / str(chapter.id)
        chunk_dir.mkdir(parents=True, exist_ok=True)

    engine = get_engine(chapter_lang)
    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        if chunk.status == ChunkStatus.done and chunk.wav_path and Path(chunk.wav_path).exists():
            continue
        wav_path = settings.chunks_dir / str(chapter.id) / f"{chunk.idx:05d}.wav"
        try:
            await asyncio.to_thread(engine.synthesize, chunk.text, chapter_voice, str(wav_path))
        except Exception as e:
            log.exception("TTS failed on chunk %s/%s", chapter.id, chunk.idx)
            async with session_scope() as session:
                fresh_chunk = (
                    await session.execute(select(Chunk).where(Chunk.id == chunk.id))
                ).scalar_one()
                fresh_chunk.status = ChunkStatus.failed
                fresh_chunk.error = str(e)[:2000]
                fresh_chapter = (
                    await session.execute(select(Chapter).where(Chapter.id == chapter.id))
                ).scalar_one()
                fresh_chapter.status = ChapterStatus.failed
                fresh_chapter.error = str(e)[:2000]
            # Re-raise so the worker's outer wrapper marks the job failed too.
            raise
        async with session_scope() as session:
            fresh_chunk = (
                await session.execute(select(Chunk).where(Chunk.id == chunk.id))
            ).scalar_one()
            fresh_chunk.wav_path = str(wav_path)
            fresh_chunk.status = ChunkStatus.done
            await update_progress(session, job_id, i / total * 0.95)

    # Enqueue assembly
    async with session_scope() as session:
        await enqueue(session, JobKind.assemble_chapter, chapter_id)


async def assemble_chapter(chapter_id: int, job_id: int) -> None:
    async with session_scope() as session:
        chapter = (await session.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one()
        if chapter.status == ChapterStatus.skipped:
            log.info("chapter %s skipped — not assembling", chapter_id)
            return
        if chapter.status == ChapterStatus.done:
            log.info("chapter %s already assembled — skipping", chapter_id)
            return
        book = await _get_book(session, chapter.book_id)
        chunks = (
            await session.execute(
                select(Chunk).where(Chunk.chapter_id == chapter.id).order_by(Chunk.idx)
            )
        ).scalars().all()
        if not chunks or any(c.status != ChunkStatus.done or not c.wav_path for c in chunks):
            raise RuntimeError("not all chunks rendered")
        wav_paths = [Path(c.wav_path) for c in chunks]
        out_dir = settings.chapters_dir / str(book.id)
        out_mp3 = out_dir / f"{chapter.idx:04d}.mp3"
        cover_path = Path(book.cover_path) if book.cover_path else None
        total_chapters = (
            await session.execute(
                select(Chapter).where(Chapter.book_id == book.id)
            )
        ).scalars().all()
        total = len(total_chapters)
        book_title = book.title
        book_author = book.author
        book_id = book.id

    await asyncio.to_thread(audio_mod.assemble_chapter_mp3, wav_paths, out_mp3)
    await asyncio.to_thread(
        audio_mod.tag_mp3,
        out_mp3,
        book_title=book_title,
        author=book_author,
        chapter_title=chapter.title,
        chapter_idx=chapter.idx,
        total_chapters=total,
        cover_path=cover_path,
    )
    duration_s = await asyncio.to_thread(audio_mod.mp3_duration_seconds, out_mp3)
    bytes_size = out_mp3.stat().st_size

    async with session_scope() as session:
        fresh_chapter = (
            await session.execute(select(Chapter).where(Chapter.id == chapter_id))
        ).scalar_one()
        fresh_chapter.mp3_path = str(out_mp3)
        fresh_chapter.duration_s = duration_s
        fresh_chapter.bytes_size = bytes_size
        fresh_chapter.status = ChapterStatus.done
        # Cleanup chunks (we have the assembled mp3 now)
        for c in (
            await session.execute(select(Chunk).where(Chunk.chapter_id == chapter_id))
        ).scalars():
            if c.wav_path:
                Path(c.wav_path).unlink(missing_ok=True)
        # If all chapters done, mark book done
        chapters = (
            await session.execute(
                select(Chapter).where(Chapter.book_id == book_id)
            )
        ).scalars().all()
        if all(ch.status == ChapterStatus.done for ch in chapters):
            book = await _get_book(session, book_id)
            book.status = BookStatus.done
        await update_progress(session, job_id, 1.0)


async def _get_book(session: AsyncSession, book_id: int) -> Book:
    return (
        await session.execute(select(Book).where(Book.id == book_id))
    ).scalar_one()


def _book_source_path(book_id: int) -> str:
    # Best-effort: the route saves with the book id and original suffix.
    for ext in (".epub", ".fb2", ".txt"):
        p = settings.originals_dir / f"{book_id}{ext}"
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"No source file for book {book_id}")


def _default_voice_for(lang: str) -> str:
    if lang.startswith("ru"):
        return settings.default_voice_ru
    return settings.default_voice_en
