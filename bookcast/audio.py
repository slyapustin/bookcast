from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from mutagen.id3 import APIC, ID3, TALB, TCON, TIT2, TPE1, TPE2, TRCK, TYER
from mutagen.mp3 import MP3

from .config import settings

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯA-Z\"'(])|\n+")


def split_for_tts(text: str, max_chars: int | None = None) -> list[str]:
    """Split text into TTS-friendly chunks bounded by sentence ends, capped at max_chars."""
    max_chars = max_chars or settings.tts_chunk_chars
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Sentence split first; then pack sentences into chunks.
    sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    chunks: list[str] = []
    cur = ""
    for s in sents:
        if len(s) > max_chars:
            # Hard-wrap a single very long sentence on commas/spaces.
            chunks.extend(_hard_wrap(s, max_chars))
            continue
        if cur and len(cur) + 1 + len(s) > max_chars:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    cur = ""
    for token in re.split(r"(?<=[,;:—\-\s])", text):
        if not token:
            continue
        if len(cur) + len(token) > max_chars and cur:
            parts.append(cur.strip())
            cur = token
        else:
            cur += token
    if cur.strip():
        parts.append(cur.strip())
    return parts


def assemble_chapter_mp3(
    wav_paths: list[Path],
    out_mp3: Path,
    *,
    bitrate: str | None = None,
    sample_rate: int | None = None,
) -> None:
    """Concatenate WAV files via ffmpeg into a single mono mp3."""
    if not wav_paths:
        raise ValueError("no input wavs")
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    concat_list = out_mp3.with_suffix(".concat.txt")
    concat_list.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in wav_paths), encoding="utf-8"
    )
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate or settings.mp3_sample_rate),
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate or settings.mp3_bitrate,
            str(out_mp3),
        ]
        subprocess.run(cmd, check=True)
    finally:
        concat_list.unlink(missing_ok=True)


def tag_mp3(
    mp3_path: Path,
    *,
    book_title: str,
    author: str | None,
    chapter_title: str,
    chapter_idx: int,
    total_chapters: int,
    cover_path: Path | None = None,
    year: str | None = None,
) -> None:
    audio = MP3(mp3_path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    tags.delall("TIT2")
    tags.delall("TALB")
    tags.delall("TPE1")
    tags.delall("TPE2")
    tags.delall("TRCK")
    tags.delall("TCON")
    tags.delall("TYER")
    tags.delall("APIC")
    tags.add(TIT2(encoding=3, text=chapter_title))
    tags.add(TALB(encoding=3, text=book_title))
    if author:
        tags.add(TPE1(encoding=3, text=author))
        tags.add(TPE2(encoding=3, text=author))
    tags.add(TRCK(encoding=3, text=f"{chapter_idx}/{total_chapters}"))
    tags.add(TCON(encoding=3, text="Audiobook"))
    if year:
        tags.add(TYER(encoding=3, text=year))
    if cover_path and cover_path.exists():
        mime = "image/jpeg" if cover_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        tags.add(
            APIC(
                encoding=3,
                mime=mime,
                type=3,
                desc="Cover",
                data=cover_path.read_bytes(),
            )
        )
    audio.save(v2_version=3)


def mp3_duration_seconds(mp3_path: Path) -> int:
    audio = MP3(mp3_path)
    return round(audio.info.length)


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None
