from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import settings
from ..tts.router import UnsupportedLanguage, all_supported_languages, get_engine, voices_for

router = APIRouter()

SAMPLE_TEXTS: dict[str, str] = {
    "en": (
        "In a hole in the ground, there lived a hobbit. "
        "Not a nasty, dirty, wet hole, filled with the ends of worms and an oozy smell, "
        "nor yet a dry, bare, sandy hole with nothing in it to sit down on or to eat: "
        "it was a hobbit-hole, and that means comfort."
    ),
    "ru": (
        "В лесу родилась ёлочка, в лесу она росла. "
        "Зимой и летом стройная, зелёная была. "
        "Метель ей пела песенку: «Спи, ёлочка, бай-бай!» "
        "Мороз снежком укутывал: «Смотри, не замерзай!»"
    ),
}


@router.get("/voice-preview/{language}/{voice}.wav")
async def voice_preview(language: str, voice: str):
    if language not in all_supported_languages():
        raise HTTPException(404)
    valid_voices = {v.id for v in voices_for(language)}
    if voice not in valid_voices:
        raise HTTPException(404)

    out = Path(settings.data_dir) / "voice_samples" / language / f"{voice}.wav"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        text = SAMPLE_TEXTS.get(language, "Hello, this is a voice preview.")
        try:
            engine = get_engine(language)
        except UnsupportedLanguage as e:
            raise HTTPException(404) from e
        await asyncio.to_thread(engine.synthesize, text, voice, str(out))

    return FileResponse(
        out,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=86400"},
    )
