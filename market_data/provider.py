"""Market-data provider abstraction used by strategies and loaders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime

from market_data.interval import Interval
from domain.candle import Candle


class MarketDataProvider(ABC):
    """Interface for broker-backed market-data adapters."""

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: Interval,
    ) -> list[Candle]:
        """Return historical candles for a symbol and interval."""
        raise NotImplementedError

    @abstractmethod
    def get_live_quote(self, symbol: str) -> list[Candle]:
        """Return the latest quote as framework candles."""
        raise NotImplementedError

    @abstractmethod
    def stream_ticks(self, symbols: list[str]) -> Iterator[list[Candle]]:
        """Yield live ticks as framework candles."""
        raise NotImplementedError
