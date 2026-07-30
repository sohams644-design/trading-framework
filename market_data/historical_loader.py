"""Historical candle loading service."""

from __future__ import annotations

from datetime import datetime

from market_data.interval import Interval
from market_data.provider import MarketDataProvider
from market_data.validator import CandleValidator
from domain.candle import Candle


class HistoricalDataLoader:
    """Retrieves and validates historical candles through a provider."""

    def __init__(
        self,
        provider: MarketDataProvider,
        validator: CandleValidator | None = None,
    ) -> None:
        self.provider = provider
        self.validator = validator or CandleValidator()

    def load(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: Interval,
    ) -> list[Candle]:
        """Load validated historical candles for a symbol."""

        candles = self.provider.get_historical_data(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )
        return self.validator.validate(candles)
