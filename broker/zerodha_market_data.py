"""Zerodha market-data provider implementation."""

from __future__ import annotations

import logging
import queue
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from config import settings
from market_data.instrument_manager import InstrumentManager
from market_data.interval import Interval
from market_data.provider import MarketDataProvider
from domain.candle import Candle

logger = logging.getLogger(__name__)

# Private marker signalling that the ticker connection ended.
_STREAM_CLOSED = object()


class ZerodhaMarketDataProvider(MarketDataProvider):
    """Market-data adapter that isolates Kite Connect from the framework."""

    def __init__(
        self,
        instrument_manager: InstrumentManager,
        kite_client: Any | None = None,
        ticker_client: Any | None = None,
    ) -> None:
        self.instrument_manager = instrument_manager
        self.kite = kite_client or self._build_kite_client()
        self._ticker = ticker_client

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
        """Yield batches of ticks for symbols, as framework candles.

        KiteTicker pushes ticks from its own thread; this generator bridges
        that to a pull interface by handing them across a queue. It yields
        ticks and nothing else: no heartbeats, no sentinel values, no empty
        batches. The generator simply ends when the connection closes.
        """

        tokens = [self.instrument_manager.get_token(symbol) for symbol in symbols]
        tick_queue: queue.Queue = queue.Queue()
        ticker = self._ticker or self._build_ticker()

        self._wire_ticker(ticker, tokens, tick_queue)
        ticker.connect(threaded=True)
        logger.info("Zerodha ticker connected for tokens %s.", tokens)

        try:
            while True:
                item = tick_queue.get()
                if item is _STREAM_CLOSED:
                    logger.info("Zerodha ticker stream closed.")
                    return
                candles = self._to_candles(item)
                if candles:
                    yield candles
        finally:
            self._close_ticker(ticker)

    @staticmethod
    def _wire_ticker(ticker: Any, tokens: list[int], tick_queue: queue.Queue) -> None:
        def on_ticks(_ws: Any, ticks: list[dict[str, Any]]) -> None:
            tick_queue.put(ticks)

        def on_connect(ws: Any, _response: Any) -> None:
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)

        def on_close(_ws: Any, code: Any, reason: Any) -> None:
            logger.warning("Zerodha ticker closed: %s %s", code, reason)
            tick_queue.put(_STREAM_CLOSED)

        def on_error(_ws: Any, code: Any, reason: Any) -> None:
            logger.warning("Zerodha ticker error: %s %s", code, reason)

        ticker.on_ticks = on_ticks
        ticker.on_connect = on_connect
        ticker.on_close = on_close
        ticker.on_error = on_error

    def _to_candles(self, ticks: list[dict[str, Any]]) -> list[Candle]:
        candles = []
        for tick in ticks:
            candle = self._tick_to_candle(tick)
            if candle is not None:
                candles.append(candle)
        return candles

    @staticmethod
    def _tick_to_candle(tick: dict[str, Any]) -> Candle | None:
        """Map one raw tick to a degenerate candle, or None if malformed.

        ``volume`` carries Zerodha's cumulative day volume unchanged; turning
        that into per-bar volume is ``TickAggregator``'s job, not the
        adapter's.
        """

        try:
            last_price = float(tick["last_price"])
            timestamp = tick.get("exchange_timestamp") or tick.get("last_trade_time")
            if not isinstance(timestamp, datetime):
                raise ValueError("tick is missing an exchange timestamp")
            return Candle(
                timestamp=timestamp,
                open=last_price,
                high=last_price,
                low=last_price,
                close=last_price,
                volume=int(tick.get("volume_traded", 0)),
            )
        except (KeyError, TypeError, ValueError) as error:
            logger.warning("Dropping malformed tick %s: %s", tick, error)
            return None

    @staticmethod
    def _close_ticker(ticker: Any) -> None:
        try:
            ticker.close()
        except Exception:
            logger.warning("Failed to close Zerodha ticker cleanly.", exc_info=True)

    @staticmethod
    def _build_kite_client() -> Any:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=settings.api_key)
        if settings.access_token:
            kite.set_access_token(settings.access_token)
        return kite

    @staticmethod
    def _build_ticker() -> Any:
        from kiteconnect import KiteTicker

        return KiteTicker(api_key=settings.api_key, access_token=settings.access_token)

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
