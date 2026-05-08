from __future__ import annotations

import logging
import threading
from functools import cached_property
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from ..config import settings
from .base import TTSError, Voice

log = logging.getLogger(__name__)

_KOKORO_VOICES = [
    ("af_heart", "Heart (US female)"),
    ("af_bella", "Bella (US female)"),
    ("af_nicole", "Nicole (US female, soft)"),
    ("af_sarah", "Sarah (US female)"),
    ("am_adam", "Adam (US male)"),
    ("am_michael", "Michael (US male)"),
    ("bf_emma", "Emma (UK female)"),
    ("bm_george", "George (UK male)"),
]

# Official release assets from the kokoro-onnx project.
_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_MODEL_URL = f"{_RELEASE}/kokoro-v1.0.onnx"
_VOICES_URL = f"{_RELEASE}/voices-v1.0.bin"


class KokoroEngine:
    language = "en"
    sample_rate = 24000

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @cached_property
    def _kokoro(self):
        try:
            from kokoro_onnx import Kokoro  # type: ignore
        except ImportError as e:
            raise TTSError(f"kokoro-onnx not installed: {e}") from e

        model_path = (
            Path(settings.kokoro_model_path)
            if settings.kokoro_model_path
            else _ensure_file(_MODEL_URL, "kokoro-v1.0.onnx")
        )
        voices_path = (
            Path(settings.kokoro_voices_path)
            if settings.kokoro_voices_path
            else _ensure_file(_VOICES_URL, "voices-v1.0.bin")
        )
        return Kokoro(str(model_path), str(voices_path))

    def voices(self) -> list[Voice]:
        return [Voice(id=v, label=label, language="en") for v, label in _KOKORO_VOICES]

    def synthesize(self, text: str, voice: str, out_path: str) -> None:
        text = text.strip()
        if not text:
            raise TTSError("empty text")
        with self._lock:
            samples, sr = self._synth_with_split(text, voice or "af_heart")
        if not isinstance(samples, np.ndarray):
            samples = np.asarray(samples, dtype=np.float32)
        sf.write(out_path, samples, sr, subtype="PCM_16")

    def _synth_with_split(self, text: str, voice: str):
        """Call Kokoro's create(); on the 510-phoneme limit, recursively split."""
        try:
            return self._kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
        except IndexError as e:
            # Kokoro's hard limit is 510 tokens; phoneme expansion can exceed our
            # character-based chunking. Bisect on a sentence/whitespace boundary
            # and concatenate.
            if "510" not in str(e) and "axis 0" not in str(e):
                raise
            return self._bisect_synth(text, voice)

    def _bisect_synth(self, text: str, voice: str):
        a, b = _bisect_text(text)
        if not a or not b:
            raise TTSError(f"cannot split text further (len={len(text)})")
        sa, sr_a = self._synth_with_split(a, voice)
        sb, sr_b = self._synth_with_split(b, voice)
        if sr_a != sr_b:
            raise TTSError("sample-rate mismatch across split")
        if not isinstance(sa, np.ndarray):
            sa = np.asarray(sa, dtype=np.float32)
        if not isinstance(sb, np.ndarray):
            sb = np.asarray(sb, dtype=np.float32)
        return np.concatenate([sa, sb]), sr_a


def _bisect_text(text: str) -> tuple[str, str]:
    """Split text near the middle, preferring sentence then word boundaries."""
    text = text.strip()
    n = len(text)
    if n < 10:
        return text, ""
    mid = n // 2
    # Sentence-end nearest the middle.
    for delim in (". ", "! ", "? ", "; ", ", "):
        left = text.rfind(delim, 0, mid + len(delim))
        right = text.find(delim, mid)
        if left != -1 and (right == -1 or mid - left <= right - mid):
            split = left + len(delim)
            return text[:split].rstrip(), text[split:].lstrip()
        if right != -1:
            split = right + len(delim)
            return text[:split].rstrip(), text[split:].lstrip()
    # Fall back to whitespace.
    space = text.rfind(" ", 0, mid)
    if space == -1:
        space = text.find(" ", mid)
    if space == -1:
        return text[:mid], text[mid:]
    return text[:space].rstrip(), text[space:].lstrip()


def _ensure_file(url: str, name: str) -> Path:
    target_dir = Path(settings.data_dir) / "models" / "kokoro"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    if target.exists() and target.stat().st_size > 0:
        return target
    log.info("downloading kokoro asset %s -> %s", url, target)
    tmp = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=600.0) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)
    tmp.rename(target)
    log.info("downloaded %s (%.1f MB)", target, target.stat().st_size / 1e6)
    return target
