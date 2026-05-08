from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from ._text import clean_text, guess_language

if TYPE_CHECKING:
    from . import ParsedBook

# Heuristic chapter starters. Order matters: more specific first.
_CHAPTER_PATTERNS = [
    # "Chapter 12", "Chapter XII", "CHAPTER 1: Title"
    re.compile(r"^\s*chapter\s+(?:[ivxlcdm]+|\d+)\b[\s.:—\-–]*(.*)$", re.IGNORECASE),
    # Russian: "Глава 1", "ГЛАВА 12 — Возвращение"
    re.compile(r"^\s*глава\s+(?:\d+|[ivxlcdm]+)\b[\s.:—\-–]*(.*)$", re.IGNORECASE),
    # Markdown headings
    re.compile(r"^\s*#{1,3}\s+(.+?)\s*$"),
    # Stand-alone numeric heading: "1.", "I.", "12 — Title"
    re.compile(r"^\s*(?:\d{1,3}|[ivxlcdm]+)\s*[.—\-–:]\s*(.*\S.*)$", re.IGNORECASE),
]

# A line that's only =/-/* (underline-style heading separator)
_UNDERLINE = re.compile(r"^[=\-*]{3,}\s*$")


def parse(path: Path) -> ParsedBook:
    from . import ParsedBook, ParsedChapter

    raw = _read(path)
    text = clean_text(raw)
    title_guess, author_guess = _guess_metadata(text)

    chapters = _split_chapters(text)
    if not chapters:
        chapters = [ParsedChapter(title=title_guess, text=text)]

    language = guess_language("\n".join(c.text for c in chapters[:3]))

    return ParsedBook(
        title=title_guess,
        author=author_guess,
        language=language,
        cover_bytes=None,
        chapters=chapters,
    )


def _read(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp1251", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _guess_metadata(text: str) -> tuple[str, str | None]:
    lines = [line for line in (line.strip() for line in text.splitlines()) if line]
    if not lines:
        return ("Untitled", None)
    title = lines[0][:200]
    author = None
    for line in lines[1:5]:
        low = line.lower()
        if low.startswith(("by ", "автор ", "автор:")):
            author = line.split(maxsplit=1)[1] if " " in line else line
            break
    return (title, author)


def _split_chapters(text: str):
    from . import ParsedChapter

    lines = text.splitlines()
    headings = _detect_headings(lines)
    if len(headings) < 2:
        return []

    chapters = []
    for hi, (line_idx, title) in enumerate(headings):
        next_idx = headings[hi + 1][0] if hi + 1 < len(headings) else len(lines)
        body_lines = lines[line_idx + 1 : next_idx]
        # If next line was an underline (===), skip it
        if body_lines and _UNDERLINE.match(body_lines[0]):
            body_lines = body_lines[1:]
        body = clean_text("\n".join(body_lines))
        if not body or len(body) < 40:
            continue
        chapters.append(ParsedChapter(title=title[:200] or f"Chapter {len(chapters) + 1}", text=body))
    return chapters


def _detect_headings(lines: list[str]) -> list[tuple[int, str]]:
    """Return [(line_index, title), ...] for likely chapter headings."""
    headings: list[tuple[int, str]] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or len(line) > 120:
            continue
        # Underline-style: a short line followed by ===/--- on the next line
        if i + 1 < len(lines) and _UNDERLINE.match(lines[i + 1]):
            headings.append((i, line))
            continue
        for pat in _CHAPTER_PATTERNS:
            m = pat.match(line)
            if m:
                tail = m.group(1).strip() if m.lastindex else ""
                title = tail or line
                headings.append((i, title))
                break
    # Prune false positives that occur inside very dense text:
    # require some blank-line separation around heading lines.
    pruned: list[tuple[int, str]] = []
    for idx, title in headings:
        prev_blank = idx == 0 or not lines[idx - 1].strip()
        next_blank = (idx + 1 >= len(lines)) or not lines[idx + 1].strip() or _UNDERLINE.match(lines[idx + 1] or "")
        if prev_blank or next_blank:
            pruned.append((idx, title))
    return pruned
