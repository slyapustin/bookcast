from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

from lxml import etree

from ._text import clean_text, guess_language

if TYPE_CHECKING:
    from . import ParsedBook, ParsedChapter

NS = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0", "l": "http://www.w3.org/1999/xlink"}


def parse(path: Path) -> ParsedBook:
    from . import ParsedBook, ParsedChapter

    tree = etree.parse(str(path))
    root = tree.getroot()
    # Some fb2 files declare no namespace; normalize lookup.
    nsmap = {"fb": root.nsmap.get(None) or NS["fb"], "l": NS["l"]}

    title = _xpath_text(root, ".//fb:title-info/fb:book-title", nsmap) or path.stem
    author = _author(root, nsmap)
    language = _xpath_text(root, ".//fb:title-info/fb:lang", nsmap)
    cover_bytes = _extract_cover(root, nsmap)

    body = root.find("fb:body", namespaces=nsmap)
    chapters: list[ParsedChapter] = []
    if body is not None:
        for idx, section in enumerate(body.findall("fb:section", namespaces=nsmap), start=1):
            chapter = _section_to_chapter(section, nsmap, default_title=f"Chapter {idx}")
            if chapter is not None:
                chapters.append(chapter)

    if not chapters and body is not None:
        # Books that put text directly in <body> without sections
        text = clean_text(_collect_text(body, nsmap))
        if text:
            chapters = [ParsedChapter(title=title, text=text)]

    if not language and chapters:
        language = guess_language("\n".join(c.text for c in chapters[:3]))

    return ParsedBook(
        title=title,
        author=author,
        language=language,
        cover_bytes=cover_bytes,
        chapters=chapters,
    )


def _section_to_chapter(section, nsmap, default_title: str):
    from . import ParsedChapter

    title_el = section.find("fb:title", namespaces=nsmap)
    if title_el is not None:
        title = clean_text(" ".join(title_el.itertext()))
    else:
        title = ""
    title = title or default_title
    text = clean_text(_collect_text(section, nsmap, skip_title=True))
    if not text or len(text) < 40:
        return None
    return ParsedChapter(title=title[:200], text=text)


_PROSE_TAGS = {"p", "v", "subtitle", "text-author", "cite"}


def _collect_text(el, nsmap, *, skip_title: bool = False) -> str:
    """Collect prose text from an fb2 element, recursing into nested sections."""
    if el is None:
        return ""
    parts: list[str] = []
    for child in el.iterchildren():
        tag = etree.QName(child).localname
        if tag == "title" and skip_title:
            continue
        if tag in _PROSE_TAGS:
            t = "".join(child.itertext()).strip()
            if t:
                parts.append(t)
        elif tag == "empty-line":
            parts.append("")
        elif tag in {"epigraph", "annotation"}:
            inner = _collect_text(child, nsmap, skip_title=False).strip()
            if inner:
                parts.append(inner)
        elif tag == "section":
            inner = _collect_text(child, nsmap, skip_title=True).strip()
            if inner:
                parts.append(inner)
    return "\n\n".join(parts)


def _xpath_text(root, xpath: str, nsmap) -> str | None:
    el = root.find(xpath, namespaces=nsmap)
    if el is None:
        return None
    text = "".join(el.itertext()).strip()
    return text or None


def _author(root, nsmap) -> str | None:
    el = root.find(".//fb:title-info/fb:author", namespaces=nsmap)
    if el is None:
        return None
    parts = []
    for tag in ("first-name", "middle-name", "last-name", "nickname"):
        node = el.find(f"fb:{tag}", namespaces=nsmap)
        if node is not None and node.text and node.text.strip():
            parts.append(node.text.strip())
    return " ".join(parts) or None


def _extract_cover(root, nsmap) -> bytes | None:
    coverpage = root.find(".//fb:title-info/fb:coverpage", namespaces=nsmap)
    if coverpage is None:
        return None
    image = coverpage.find("fb:image", namespaces=nsmap)
    if image is None:
        return None
    href = image.get(f"{{{nsmap['l']}}}href") or image.get("href")
    if not href:
        return None
    binary_id = href.lstrip("#")
    binary = root.find(f".//fb:binary[@id='{binary_id}']", namespaces=nsmap)
    if binary is None or not binary.text:
        return None
    try:
        return base64.b64decode(binary.text)
    except Exception:
        return None
