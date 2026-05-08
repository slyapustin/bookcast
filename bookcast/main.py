from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routes.book import router as book_router
from .routes.feed import router as feed_router
from .routes.library import router as library_router
from .routes.preview import router as preview_router
from .routes.upload import router as upload_router


def create_app() -> FastAPI:
    app = FastAPI(title="Bookcast", version="0.1.0")
    app.include_router(library_router)
    app.include_router(upload_router)
    app.include_router(book_router)
    app.include_router(feed_router)
    app.include_router(preview_router)

    static_dir = Path(__file__).parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    settings.ensure_dirs()
    return app


app = create_app()
