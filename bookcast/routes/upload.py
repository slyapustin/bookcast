from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..deps import db_session, templates
from ..models import Book, BookStatus, JobKind
from ..parsers import SUPPORTED, UnsupportedFormat, detect_format
from ..queue import enqueue

router = APIRouter()


@router.get("/upload")
async def upload_form(request: Request):
    return templates.TemplateResponse(
        request, "upload.html", {"supported": sorted(SUPPORTED)}
    )


@router.post("/upload")
async def upload_submit(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(db_session),
):
    filename = Path(file.filename or "").name
    if not filename:
        return _error(request, "Missing filename")
    try:
        fmt = detect_format(Path(filename))
    except UnsupportedFormat:
        return _error(request, f"Unsupported format. Use: {', '.join(sorted(SUPPORTED))}")

    book = Book(
        title=Path(filename).stem,
        author=None,
        language="en",
        source_path="",  # filled below
        source_format=fmt,
        status=BookStatus.pending,
        feed_token=secrets.token_urlsafe(24),
    )
    session.add(book)
    await session.flush()

    out_path = settings.originals_dir / f"{book.id}.{fmt}"
    contents = await file.read()
    out_path.write_bytes(contents)
    book.source_path = str(out_path)

    await enqueue(session, JobKind.parse_book, book.id)
    return RedirectResponse(f"/book/{book.id}", status_code=303)


def _error(request: Request, msg: str):
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"supported": sorted(SUPPORTED), "error": msg},
        status_code=400,
    )
