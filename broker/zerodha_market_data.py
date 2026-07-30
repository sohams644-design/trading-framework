"""Zerodha market-data provider implementation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from config import settings
from market_data.instrument_manager import InstrumentManager
from market_data.interval import Interval
from market_data.provider import MarketDataProvider
from domain.candle import Candle


class ZerodhaMarketDataProvider(MarketDataProvider):
    """Market-data adapter that isolates Kite Connect from the framework."""

    def __init__(
        self,
        instrument_manager: InstrumentManager,
        kite_client: Any | None = None,
    ) -> None:
        self.instrument_manager = instrument_manager
        self.kite = kite_client or self._build_kite_client()

    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: Interval,
    ) -> list[Candle]:
        """Fetch historical candles from Zerodha and map them to Candle objects."""

        instrument_token = self.instrument_manager.get_token(symbol)
        candles = self.kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval.value,
        )
        return [self._to_candle(candle) for candle in candles]

    def get_live_quote(self, symbol: str) -> list[Candle]:
        """Return the live quote for a symbol as a framework candle."""

        instrument = self.instrument_manager.get_by_symbol(symbol)
        quote_key = f"{instrument.exchange}:{instrument.symbol}"
        quote = self.kite.quote([quote_key])[quote_key]
        return [self._quote_to_candle(quote)]

    def stream_ticks(self, symbols: list[str]) -> Iterator[list[Candle]]:
        """Yield ticks for symbols.

        WebSocket streaming is intentionally exposed as an iterator boundary here;
        wiring a concrete ticker client belongs in a future real-time data sprint.
        """

        raise NotImplementedError("Zerodha tick streaming is not configured yet.")

    @staticmethod
    def _build_kite_client() -> Any:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=settings.api_key)
        if settings.access_token:
            kite.set_access_token(settings.access_token)
        return kite

    @staticmethod
    def _to_candle(payload: dict[str, Any]) -> Candle:
        return Candle(
            timestamp=payload["date"],
            open=float(payload["open"]),
            high=float(payload["high"]),
            low=float(payload["low"]),
            close=float(payload["close"]),
            volume=int(payload["volume"]),
        )

    @staticmethod
    def _quote_to_candle(payload: dict[str, Any]) -> Candle:
        last_price = float(payload["last_price"])
        ohlc = payload.get("ohlc", {})
        return Candle(
            timestamp=payload["timestamp"],
            open=float(ohlc.get("open", last_price)),
            high=float(ohlc.get("high", last_price)),
            low=float(ohlc.get("low", last_price)),
            close=last_price,
            volume=int(payload.get("volume", 0)),
        )
