from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import db_session, templates
from ..models import Book

router = APIRouter()


@router.get("/")
async def library(
    request: Request,
    session: AsyncSession = Depends(db_session),
):
    books = (
        await session.execute(select(Book).order_by(Book.created_at.desc()))
    ).scalars().all()
    return templates.TemplateResponse(request, "library.html", {"books": books})
