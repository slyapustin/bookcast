from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BookStatus(enum.StrEnum):
    pending = "pending"
    parsing = "parsing"
    ready_to_render = "ready_to_render"
    rendering = "rendering"
    done = "done"
    failed = "failed"


class ChapterStatus(enum.StrEnum):
    pending = "pending"
    rendering = "rendering"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class ChunkStatus(enum.StrEnum):
    pending = "pending"
    done = "done"
    failed = "failed"


class JobKind(enum.StrEnum):
    parse_book = "parse_book"
    tts_chapter = "tts_chapter"
    assemble_chapter = "assemble_chapter"


class JobState(enum.StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    voice: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_path: Mapped[str] = mapped_column(String(1024))
    source_format: Mapped[str] = mapped_column(String(8))  # epub, fb2, txt
    status: Mapped[BookStatus] = mapped_column(
        Enum(BookStatus, native_enum=False), default=BookStatus.pending
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    feed_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="Chapter.idx"
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)  # 1-based
    title: Mapped[str] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    mp3_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ChapterStatus] = mapped_column(
        Enum(ChapterStatus, native_enum=False), default=ChapterStatus.pending
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    book: Mapped[Book] = relationship(back_populates="chapters")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="Chunk.idx"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    wav_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[ChunkStatus] = mapped_column(
        Enum(ChunkStatus, native_enum=False), default=ChunkStatus.pending
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    chapter: Mapped[Chapter] = relationship(back_populates="chunks")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[JobKind] = mapped_column(Enum(JobKind, native_enum=False), index=True)
    ref_id: Mapped[int] = mapped_column(Integer, index=True)
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, native_enum=False), default=JobState.pending, index=True
    )
    progress: Mapped[float] = mapped_column(default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
