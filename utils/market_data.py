"""Backward-compatible market-data helper functions."""

from __future__ import annotations

from datetime import datetime

from broker.zerodha_market_data import ZerodhaMarketDataProvider
from market_data.historical_loader import HistoricalDataLoader
from market_data.instrument_manager import InstrumentManager
from market_data.interval import Interval
from domain.candle import Candle

_default_manager: InstrumentManager | None = None
_default_provider: ZerodhaMarketDataProvider | None = None


def get_token(symbol: str) -> int:
    """Return the instrument token for a trading symbol."""

    return _get_default_manager().get_token(symbol)


def get_history(
    symbol: str,
    from_date: datetime,
    to_date: datetime,
    interval: Interval = Interval.FIVE_MINUTE,
) -> list[Candle]:
    """Fetch validated historical candles."""

    loader = HistoricalDataLoader(_get_default_provider())
    return loader.load(symbol, from_date, to_date, interval)


def _get_default_manager() -> InstrumentManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = InstrumentManager()
    return _default_manager


def _get_default_provider() -> ZerodhaMarketDataProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = ZerodhaMarketDataProvider(_get_default_manager())
    return _default_provider
