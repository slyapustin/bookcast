from __future__ import annotations

import threading
from functools import cached_property
from pathlib import Path

import soundfile as sf

from ..config import settings
from .base import TTSError, Voice

_SILERO_RU_VOICES = [
    ("xenia", "Xenia (female)"),
    ("baya", "Baya (female)"),
    ("kseniya", "Kseniya (female)"),
    ("aidar", "Aidar (male)"),
    ("eugene", "Eugene (male)"),
]


class SileroEngine:
    """Russian TTS via the official Silero models repository.

    Pinned to ``v4_ru`` (the ``speaker`` argument for ``torch.hub.load`` with
    ``model='silero_tts', language='ru'``). The Silero project is on hold and v3
    vs v4 model files differ — pin explicitly so re-downloads stay deterministic.
    Models are downloaded into ``settings.data_dir / "models"``.
    """

    language = "ru"
    sample_rate = 24000  # supports 8/24/48 kHz

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @cached_property
    def _model(self):
        try:
            import torch
        except ImportError as e:
            raise TTSError(f"torch not installed: {e}") from e
        models_dir = Path(settings.data_dir) / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        torch.hub.set_dir(str(models_dir))
        model, _example_text = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language="ru",
            speaker="v4_ru",
            trust_repo=True,
        )
        model.to(torch.device("cpu"))
        return model

    def voices(self) -> list[Voice]:
        return [Voice(id=v, label=label, language="ru") for v, label in _SILERO_RU_VOICES]

    def synthesize(self, text: str, voice: str, out_path: str) -> None:
        text = text.strip()
        if not text:
            raise TTSError("empty text")
        with self._lock:
            audio = self._model.apply_tts(
                text=text,
                speaker=voice or "xenia",
                sample_rate=self.sample_rate,
                put_accent=True,
                put_yo=True,
            )
        sf.write(out_path, audio.cpu().numpy(), self.sample_rate, subtype="PCM_16")
