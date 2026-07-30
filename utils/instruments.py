"""Instrument lookup helpers."""

from __future__ import annotations

from market_data.instrument_manager import InstrumentManager

_default_manager: InstrumentManager | None = None


def get_token(symbol: str) -> int:
    """Return the instrument token for a trading symbol."""

    return _get_default_manager().get_token(symbol)


def _get_default_manager() -> InstrumentManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = InstrumentManager()
    return _default_manager
