from __future__ import annotations

import re

# Shared text helpers: HTML→text, whitespace cleanup, language guessing.

_WS = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")


def clean_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS.sub(" ", s)
    s = _BLANKS.sub("\n\n", s)
    # Drop trailing/leading whitespace per line
    s = "\n".join(line.strip() for line in s.split("\n"))
    return s.strip()


def guess_language(text: str) -> str | None:
    sample = text[:5000].strip()
    if not sample:
        return None
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        lang = detect(sample)
    except Exception:
        return None
    # Normalize a few common variants
    return {"uk": "uk", "ru": "ru", "en": "en"}.get(lang, lang)
