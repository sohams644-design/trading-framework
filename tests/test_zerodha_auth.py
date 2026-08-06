import json
from datetime import date

import pytest

from broker.zerodha_auth import ZerodhaAuthenticator, ZerodhaAuthError, ZerodhaTokenStore

TODAY = date(2026, 8, 6)
YESTERDAY = date(2026, 8, 5)


def _store(tmp_path) -> ZerodhaTokenStore:
    return ZerodhaTokenStore(tmp_path / "token.json")


# --- ZerodhaTokenStore ---


def test_token_store_returns_none_when_no_cache_exists(tmp_path):
    assert _store(tmp_path).load_for(TODAY) is None


def test_token_store_round_trips_a_token_issued_today(tmp_path):
    store = _store(tmp_path)
    store.save("abc123", TODAY)

    assert store.load_for(TODAY) == "abc123"


def test_token_store_rejects_a_token_issued_on_an_earlier_day(tmp_path):
    store = _store(tmp_path)
    store.save("stale", YESTERDAY)

    # Kite tokens expire daily, so yesterday's cache must not be reused.
    assert store.load_for(TODAY) is None


def test_token_store_creates_missing_parent_directories(tmp_path):
    store = ZerodhaTokenStore(tmp_path / "nested" / "dir" / "token.json")
    store.save("abc123", TODAY)

    assert store.load_for(TODAY) == "abc123"


def test_token_store_ignores_a_corrupt_cache_instead_of_crashing(tmp_path):
    store = _store(tmp_path)
    store.path.write_text("not json at all")

    assert store.load_for(TODAY) is None


def test_token_store_ignores_a_cache_missing_expected_keys(tmp_path):
    store = _store(tmp_path)
    store.path.write_text(json.dumps({"unexpected": "shape"}))

    assert store.load_for(TODAY) is None


# --- ZerodhaAuthenticator ---


def _authenticator(tmp_path, prompt=None, today=TODAY) -> ZerodhaAuthenticator:
    return ZerodhaAuthenticator(
        api_key="key",
        api_secret="secret",
        token_store=_store(tmp_path),
        prompt=prompt or (lambda _: "request-token"),
        today=lambda: today,
    )


def test_authenticator_requires_an_api_key(tmp_path):
    with pytest.raises(ZerodhaAuthError, match="API_KEY"):
        ZerodhaAuthenticator(api_key="", api_secret="secret", token_store=_store(tmp_path))


def test_authenticator_reuses_a_cached_token_without_prompting(tmp_path):
    store = _store(tmp_path)
    store.save("cached-token", TODAY)

    def explode(_message):
        raise AssertionError("should not prompt when a valid token is cached")

    authenticator = ZerodhaAuthenticator(
        api_key="key",
        api_secret="secret",
        token_store=store,
        prompt=explode,
        today=lambda: TODAY,
    )

    assert authenticator.access_token() == "cached-token"


def test_authenticator_prompts_and_caches_when_the_token_expired(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save("stale-token", YESTERDAY)
    prompts: list[str] = []

    _install_fake_kiteconnect(monkeypatch, expected_request_token="request-token")

    authenticator = ZerodhaAuthenticator(
        api_key="key",
        api_secret="secret",
        token_store=store,
        prompt=lambda message: prompts.append(message) or "request-token",
        today=lambda: TODAY,
    )

    assert authenticator.access_token() == "fresh-token"
    assert prompts, "operator should be prompted for a request_token"
    # The fresh token is cached so the rest of the day needs no further login.
    assert store.load_for(TODAY) == "fresh-token"


def test_authenticator_requires_api_secret_to_exchange_a_request_token(tmp_path):
    # An explicitly empty credential must stay empty rather than falling back
    # to the ambient environment, so this holds with or without a local .env.
    authenticator = ZerodhaAuthenticator(
        api_key="key",
        api_secret="",
        token_store=_store(tmp_path),
        prompt=lambda _: "request-token",
        today=lambda: TODAY,
    )

    with pytest.raises(ZerodhaAuthError, match="API_SECRET"):
        authenticator.access_token()


def test_authenticator_rejects_an_empty_request_token(tmp_path, monkeypatch):
    _install_fake_kiteconnect(monkeypatch, expected_request_token="request-token")
    authenticator = _authenticator(tmp_path, prompt=lambda _: "   ")

    with pytest.raises(ZerodhaAuthError, match="No request_token"):
        authenticator.access_token()


def test_authenticator_wraps_a_failed_session_exchange(tmp_path, monkeypatch):
    _install_fake_kiteconnect(monkeypatch, fail=True)
    authenticator = _authenticator(tmp_path)

    with pytest.raises(ZerodhaAuthError, match="session exchange failed"):
        authenticator.access_token()


def _install_fake_kiteconnect(monkeypatch, expected_request_token=None, fail=False):
    """Install a stand-in kiteconnect module so no SDK or network is needed."""

    import sys
    import types

    module = types.ModuleType("kiteconnect")

    class FakeKiteConnect:
        def __init__(self, api_key):
            self.api_key = api_key
            self.access_token = None

        def login_url(self):
            return "https://kite.zerodha.com/connect/login?api_key=key"

        def set_access_token(self, token):
            self.access_token = token

        def generate_session(self, request_token, api_secret):
            if fail:
                raise RuntimeError("invalid token")
            assert request_token == expected_request_token
            return {"access_token": "fresh-token"}

    class FakeKiteTicker:
        def __init__(self, api_key, access_token):
            self.api_key = api_key
            self.access_token = access_token

    module.KiteConnect = FakeKiteConnect
    module.KiteTicker = FakeKiteTicker
    monkeypatch.setitem(sys.modules, "kiteconnect", module)


def test_authenticator_builds_clients_from_a_cached_token(tmp_path, monkeypatch):
    _install_fake_kiteconnect(monkeypatch)
    store = _store(tmp_path)
    store.save("cached-token", TODAY)
    authenticator = ZerodhaAuthenticator(
        api_key="key", api_secret="secret", token_store=store, today=lambda: TODAY
    )

    kite = authenticator.kite_client()
    ticker = authenticator.ticker_client()

    assert kite.access_token == "cached-token"
    assert ticker.access_token == "cached-token"
    assert ticker.api_key == "key"
