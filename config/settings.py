"""Application configuration defaults for the trading framework."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    api_key: str | None = os.getenv("API_KEY")
    access_token: str | None = os.getenv("ACCESS_TOKEN")
    instrument_file: str = os.getenv("INSTRUMENT_FILE", "data/instruments.csv")
    log_dir: str = os.getenv("LOG_DIR", "data/logs")


settings = Settings()
