from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Voice:
    id: str
    label: str
    language: str


class TTSEngine(Protocol):
    """Synthesizes text to a 24 kHz mono WAV file at out_path."""

    language: str

    def voices(self) -> list[Voice]: ...

    def synthesize(self, text: str, voice: str, out_path: str) -> None: ...


class TTSError(RuntimeError):
    pass
