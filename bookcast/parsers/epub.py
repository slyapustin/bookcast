from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from ._text import clean_text, guess_language

if TYPE_CHECKING:
    from . import ParsedBook, ParsedChapter


def parse(path: Path) -> ParsedBook:
    # Imports inside function to keep module-load cheap and avoid ebooklib
    # warnings at import time.
    import warnings

    from ebooklib import ITEM_DOCUMENT, epub

    from . import ParsedBook, ParsedChapter

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = epub.read_epub(str(path))

    title = _meta(book, "title") or path.stem
    author = _meta(book, "creator")
    language = _meta(book, "language") or None

    cover_bytes = _extract_cover(book)

    spine_ids = [item_id for item_id, _linear in book.spine]
    spine_items = [book.get_item_with_id(sid) for sid in spine_ids]
    spine_items = [it for it in spine_items if it is not None and it.get_type() == ITEM_DOCUMENT]

    # Build href→title lookup from TOC for nicer chapter names.
    toc_titles = _flatten_toc(book.toc)

    chapters: list[ParsedChapter] = []
    for item in spine_items:
        html = item.get_body_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = clean_text(soup.get_text("\n"))
        if not text or len(text) < 40:
            continue
        href = item.get_name()
        toc_title = toc_titles.get(href) or toc_titles.get(href.split("#", 1)[0])
        split_chapters = _split_html_document_by_chapter_headings(soup)
        if split_chapters:
            chapters.extend(split_chapters)
            continue

        title_guess = (
            toc_title
            or _first_heading(soup)
            or _first_nonempty_line(text)
            or f"Chapter {len(chapters) + 1}"
        )
        chapters.append(ParsedChapter(title=title_guess[:200], text=text))

    if not chapters:
        # Fall back to a single chapter with everything we could read.
        all_text = "\n\n".join(
            clean_text(BeautifulSoup(it.get_body_content(), "lxml").get_text("\n"))
            for it in spine_items
        ).strip()
        chapters = [ParsedChapter(title=title, text=all_text)] if all_text else []

    if not language and chapters:
        language = guess_language("\n".join(c.text for c in chapters[:3]))

    return ParsedBook(
        title=title,
        author=author,
        language=language,
        cover_bytes=cover_bytes,
        chapters=chapters,
    )


def _meta(book, name: str) -> str | None:
    items = book.get_metadata("DC", name)
    if not items:
        return None
    value = items[0][0]
    return value.strip() if isinstance(value, str) and value.strip() else None


def _extract_cover(book) -> bytes | None:
    from ebooklib import ITEM_COVER, ITEM_IMAGE

    for it in book.get_items_of_type(ITEM_COVER):
        data = it.get_content()
        if data:
            return bytes(data)
    # Some epubs only mark cover via metadata id reference
    cover_meta = book.get_metadata("OPF", "cover")
    if cover_meta:
        cover_id = cover_meta[0][1].get("content")
        if cover_id:
            it = book.get_item_with_id(cover_id)
            if it is not None:
                return bytes(it.get_content())
    # Last resort: first image item
    for it in book.get_items_of_type(ITEM_IMAGE):
        data = it.get_content()
        if data:
            return bytes(data)
    return None


def _split_html_document_by_chapter_headings(soup: BeautifulSoup) -> list[ParsedChapter]:
    """Split EPUB spine documents that contain several real book chapters.

    Some Project Gutenberg EPUBs group multiple book chapters into one HTML
    document. If we treat each spine file as one audio episode, the UI appears
    to jump from chapter 1 → 4 → 10. Split on explicit chapter headings when a
    single document contains more than one of them.
    """
    from . import ParsedChapter

    headings = [
        h
        for h in soup.find_all(("h1", "h2", "h3"))
        if _is_chapter_heading(h.get_text(" ", strip=True))
    ]
    if len(headings) < 2:
        return []

    chapters: list[ParsedChapter] = []
    for i, heading in enumerate(headings):
        next_heading = headings[i + 1] if i + 1 < len(headings) else None
        parts = [heading.get_text("\n", strip=True)]
        node = heading.next_sibling
        while node is not None and node is not next_heading:
            if hasattr(node, "get_text"):
                text = node.get_text("\n", strip=True)
            else:
                text = str(node).strip()
            if text:
                parts.append(text)
            node = node.next_sibling
        text = clean_text("\n".join(parts))
        if text and len(text) >= 40:
            title = heading.get_text(" ", strip=True) or f"Chapter {len(chapters) + 1}"
            chapters.append(ParsedChapter(title=title[:200], text=text))
    return chapters


def _is_chapter_heading(text: str) -> bool:
    return bool(re.match(r"^(chapter\s+\d+\b|epilogue\b)", text.strip(), re.IGNORECASE))


def _flatten_toc(toc) -> dict[str, str]:
    """Map href → title from possibly nested TOC structure."""
    out: dict[str, str] = {}

    def walk(items):
        for item in items:
            if isinstance(item, tuple):
                section, children = item[0], item[1] if len(item) > 1 else []
                href = getattr(section, "href", None)
                if href:
                    out[href] = getattr(section, "title", "") or out.get(href, "")
                walk(children)
            else:
                href = getattr(item, "href", None)
                if href:
                    out[href] = getattr(item, "title", "") or out.get(href, "")

    walk(toc or [])
    return out


def _first_heading(soup: BeautifulSoup) -> str | None:
    for tag in ("h1", "h2", "h3"):
        node = soup.find(tag)
        if node and node.get_text(strip=True):
            return node.get_text(" ", strip=True)
    return None


def _first_nonempty_line(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) <= 200:
            return line
    return None
