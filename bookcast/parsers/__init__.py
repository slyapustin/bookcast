from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import epub as epub_parser
from . import fb2 as fb2_parser
from . import txt as txt_parser


@dataclass
class ParsedChapter:
    title: str
    text: str


@dataclass
class ParsedBook:
    title: str
    author: str | None
    language: str | None
    cover_bytes: bytes | None
    chapters: list[ParsedChapter] = field(default_factory=list)


SUPPORTED = {".epub", ".fb2", ".txt"}


class UnsupportedFormat(ValueError):
    pass


def detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise UnsupportedFormat(f"Unsupported format: {suffix}")
    return suffix.lstrip(".")


def parse(path: Path) -> ParsedBook:
    fmt = detect_format(path)
    if fmt == "epub":
        return epub_parser.parse(path)
    if fmt == "fb2":
        return fb2_parser.parse(path)
    if fmt == "txt":
        return txt_parser.parse(path)
    raise UnsupportedFormat(fmt)


__all__ = [
    "SUPPORTED",
    "ParsedBook",
    "ParsedChapter",
    "UnsupportedFormat",
    "detect_format",
    "parse",
]
