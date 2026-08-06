"""Zerodha session authentication and daily access-token caching.

Kite access tokens expire every day. Obtaining a new one requires exchanging
a ``request_token``, which only exists after a human logs in through a
browser -- that step is deliberately not automatable, and this module does
not try to work around it. What it does remove is the need to edit code or
environment files each morning: a token is cached for the day it was issued
and reused until it expires.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


class ZerodhaAuthError(RuntimeError):
    """Raised when a Zerodha session cannot be established."""


class ZerodhaTokenStore:
    """Caches a daily access token on disk.

    The cache file contains a live credential. It is written under ``data/``
    and must never be committed; ``.gitignore`` excludes it.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or settings.token_file)

    def load_for(self, today: date) -> str | None:
        """Return the cached token if it was issued on the given date."""

        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text())
            issued_on = date.fromisoformat(payload["issued_on"])
            token = payload["access_token"]
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as error:
            logger.warning("Ignoring unreadable token cache at %s: %s", self.path, error)
            return None

        if issued_on != today:
            logger.info("Cached Zerodha token expired (issued %s).", issued_on)
            return None
        return token

    def save(self, access_token: str, today: date) -> None:
        """Cache an access token against the date it was issued."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"access_token": access_token, "issued_on": today.isoformat()})
        )
        logger.info("Cached Zerodha access token at %s.", self.path)


class ZerodhaAuthenticator:
    """Resolves a usable Zerodha session, reusing today's token when possible."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        token_store: ZerodhaTokenStore | None = None,
        prompt: Callable[[str], str] = input,
        today: Callable[[], date] = date.today,
    ) -> None:
        # `is None` rather than `or`: an explicitly supplied empty credential
        # must stay empty and fail loudly, not silently fall back to the
        # environment. That also keeps tests independent of any local .env.
        self.api_key = settings.api_key if api_key is None else api_key
        self.api_secret = settings.api_secret if api_secret is None else api_secret
        self.token_store = token_store or ZerodhaTokenStore()
        self._prompt = prompt
        self._today = today
        if not self.api_key:
            raise ZerodhaAuthError("API_KEY is not configured.")

    def access_token(self) -> str:
        """Return today's access token, prompting for a login only if needed."""

        today = self._today()
        cached = self.token_store.load_for(today)
        if cached:
            logger.info("Reusing cached Zerodha access token for %s.", today)
            return cached

        token = self._interactive_login()
        self.token_store.save(token, today)
        return token

    def kite_client(self, access_token: str | None = None) -> Any:
        """Return a KiteConnect client authenticated for today."""

        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=self.api_key)
        kite.set_access_token(access_token or self.access_token())
        return kite

    def ticker_client(self, access_token: str | None = None) -> Any:
        """Return a KiteTicker client authenticated for today."""

        from kiteconnect import KiteTicker

        return KiteTicker(
            api_key=self.api_key, access_token=access_token or self.access_token()
        )

    def _interactive_login(self) -> str:
        """Walk the operator through Kite's browser login, once per day.

        The request token can only be produced by a human completing the
        broker's own login page. This prints the URL and reads back the
        token the operator is redirected to; no credentials pass through
        this process.
        """

        if not self.api_secret:
            raise ZerodhaAuthError("API_SECRET is not configured.")

        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=self.api_key)
        print("\nZerodha login required (tokens expire daily).")
        print(f"1. Open: {kite.login_url()}")
        print("2. Log in, then copy the request_token from the redirect URL.\n")
        request_token = self._prompt("request_token: ").strip()
        if not request_token:
            raise ZerodhaAuthError("No request_token provided.")

        try:
            session = kite.generate_session(
                request_token=request_token, api_secret=self.api_secret
            )
        except Exception as error:
            raise ZerodhaAuthError(f"Zerodha session exchange failed: {error}") from error

        return session["access_token"]
