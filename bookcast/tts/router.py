from __future__ import annotations

from functools import cache

from .base import TTSEngine, Voice


class UnsupportedLanguage(ValueError):
    pass


@cache
def get_engine(language: str) -> TTSEngine:
    lang = (language or "en").lower().split("-")[0]
    if lang in {"en", "english"}:
        from .kokoro import KokoroEngine

        return KokoroEngine()
    if lang in {"ru", "russian", "uk"}:
        # Ukrainian falls back to Silero ru — closer than Kokoro en. Document later.
        from .silero import SileroEngine

        return SileroEngine()
    raise UnsupportedLanguage(f"No TTS engine configured for language: {language}")


def voices_for(language: str) -> list[Voice]:
    return get_engine(language).voices()


def all_supported_languages() -> list[str]:
    return ["en", "ru"]
