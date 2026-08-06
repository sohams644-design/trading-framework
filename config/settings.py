"""Application configuration defaults for the trading framework."""

from __future__ import annotations

from dataclasses import dataclass
import os

try:  # Optional: a .env file is convenient locally but never required.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - exercised only without python-dotenv
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables.

    Values are read once at import. A ``.env`` file is loaded first when
    python-dotenv is installed, so local development needs no exported
    shell variables.
    """

    api_key: str | None = os.getenv("API_KEY")
    api_secret: str | None = os.getenv("API_SECRET")
    access_token: str | None = os.getenv("ACCESS_TOKEN")
    instrument_file: str = os.getenv("INSTRUMENT_FILE", "data/instruments.csv")
    log_dir: str = os.getenv("LOG_DIR", "data/logs")
    token_file: str = os.getenv("TOKEN_FILE", "data/zerodha_token.json")


settings = Settings()
