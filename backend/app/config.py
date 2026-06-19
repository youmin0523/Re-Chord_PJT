"""Application settings (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# NOTE: ``.env`` is loaded into os.environ by ``backend/app/__init__.py`` (the
# earliest import point) so os.environ-readers see it before this module runs.


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    models_dir: Path = Field(default=PROJECT_ROOT / "data" / "models")

    ytdlp_cookies_from_browser: str = Field(default="")

    max_upload_bytes: int = Field(default=1_073_741_824)
    max_concurrent_jobs: int = Field(default=1)

    # Minimum source duration. Clips shorter than this break the separation
    # models (e.g. bs_roformer's STFT/overlap windows expect >~8s) — reject
    # early with a clear 400 instead of a 500 deep in model inference.
    min_audio_duration_sec: float = Field(default=10.0)

    separator_use_cuda: bool = Field(default=True)
    separator_use_fp16: bool = Field(default=True)
    separator_default_model: str = Field(default="MDX23C-InstVoc-HQ.ckpt")

    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=7860)

    # Extra browser origins allowed to call the API cross-origin, on top of
    # the always-allowed localhost/127.0.0.1 (dev). Comma-separated, exact
    # scheme+host[+port], no trailing slash. The deployed frontend (Vercel /
    # custom domain) MUST be listed here or the browser blocks every
    # response. Example:
    #   CORS_ALLOW_ORIGINS=https://youmin.site,https://www.youmin.site,https://re-chord.vercel.app
    cors_allow_origins: str = Field(default="")

    # Shared-secret that locks the mutating /ops/* endpoints once the API is
    # publicly exposed. Read here (via .env) AND honoured as a raw env var by
    # main.py. Empty = Phase A (no gate).
    rechord_ops_token: str = Field(default="")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    # Chat (OpenAI worship/music assistant)
    openai_api_key: str = Field(default="")
    openai_chat_model: str = Field(default="gpt-4o-mini")
    openai_max_tokens: int = Field(default=1200)
    openai_temperature: float = Field(default=0.3)
    chat_rate_limit_per_minute: int = Field(default=20)
    chat_rate_limit_burst: int = Field(default=6)
    chat_history_max_messages: int = Field(default=30)
    chat_tool_calling_enabled: bool = Field(default=True)
    chat_lyrics_full_on_request: bool = Field(default=True)
    tavily_api_key: str = Field(default="")
    web_search_provider: Literal["tavily", "none"] = Field(default="tavily")

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def stems_dir(self) -> Path:
        return self.data_dir / "stems"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


settings = Settings()
