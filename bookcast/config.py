from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BOOKCAST_", extra="ignore")

    data_dir: Path = Path("./data")
    db_url: str = "sqlite+aiosqlite:///./data/bookcast.db"
    db_url_sync: str = "sqlite:///./data/bookcast.db"

    # Public-facing base URL the iPhone will reach. Override on the Mac:
    #   BOOKCAST_BASE_URL=https://bookcast.<tailnet>.ts.net
    base_url: str = "http://localhost:8000"

    secret_key: str = "dev-only-change-me"
    session_max_age_s: int = 60 * 60 * 24 * 30
    magic_link_max_age_s: int = 60 * 30

    allowed_emails: list[str] = Field(default_factory=list)

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "bookcast@localhost"

    # Kokoro model paths. The kokoro-onnx package downloads into ~/.cache by default
    # if these are unset; pinning gives reproducibility.
    kokoro_model_path: str | None = None
    kokoro_voices_path: str | None = None

    # Default voices per language
    default_voice_en: str = "af_heart"
    default_voice_ru: str = "xenia"

    tts_chunk_chars: int = 480
    tts_max_parallel_chapters: int = 1
    mp3_bitrate: str = "64k"
    mp3_sample_rate: int = 24000

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def chapters_dir(self) -> Path:
        return self.data_dir / "chapters"

    @property
    def chunks_dir(self) -> Path:
        return self.data_dir / "chunks"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.originals_dir,
            self.chapters_dir,
            self.chunks_dir,
            self.covers_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
