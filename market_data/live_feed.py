"""Live market feed: turns a broker tick stream into an Iterable[Candle]."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterator
from datetime import datetime

from config.live_feed import LiveFeedConfig
from domain.candle import Candle
from market_data.provider import MarketDataProvider
from market_data.tick_aggregator import TickAggregator
from market_data.validator import CandleValidator

logger = logging.getLogger(__name__)

# Private queue markers. Neither ever escapes this module.
_SENTINEL = object()


class _FeedFailure:
    """Carries a drain-thread exception back to the consuming thread."""

    __slots__ = ("error",)

    def __init__(self, error: Exception) -> None:
        self.error = error


class LiveMarketFeed:
    """Yields completed candles from a live broker tick stream.

    This is the live counterpart to ``Replay``: both are simply
    ``Iterable[Candle]``, so ``RuntimeEngine`` cannot tell them apart.

    A broker tick stream is push-based and blocking, while the runtime is
    pull-based and needs to wake up periodically to close an elapsed candle.
    This class bridges the two with a private queue drained by a private
    background thread. The queue, the thread, and the sentinel used to end
    it are implementation details: nothing outside this class can observe
    them, and every layer above remains single-threaded.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        symbol: str,
        config: LiveFeedConfig | None = None,
        aggregator: TickAggregator | None = None,
        validator: CandleValidator | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.symbol = symbol.upper()
        self.config = config or LiveFeedConfig()
        self._provider = provider
        self._aggregator = aggregator or TickAggregator(
            self.config.interval, self.config.session
        )
        self._validator = validator or CandleValidator()
        self._now = now or datetime.now
        self._queue: queue.Queue = queue.Queue()
        self._drain_thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._first_candle_seen = False

    def __iter__(self) -> Iterator[Candle]:
        """Yield completed candles until the session ends or the feed stops."""

        if self._drain_thread is not None:
            raise RuntimeError("A LiveMarketFeed can only be iterated once.")

        self._start_drain()
        try:
            yield from self._consume()
        finally:
            self._cleanup_drain()

    def stop(self) -> None:
        """Request a graceful shutdown of the feed."""

        if self._stop_requested.is_set():
            return
        self._stop_requested.set()
        logger.info("Live feed stop requested for %s.", self.symbol)

    def _consume(self) -> Iterator[Candle]:
        while not self._stop_requested.is_set():
            try:
                item = self._queue.get(timeout=self.config.poll_timeout_seconds)
            except queue.Empty:
                candle = self._flush_if_elapsed()
                if candle is not None:
                    yield candle
                if self._market_has_closed():
                    logger.info("Market closed; ending live feed for %s.", self.symbol)
                    break
                continue

            if item is _SENTINEL:
                break

            if isinstance(item, _FeedFailure):
                final = self._flush()
                if final is not None:
                    yield final
                raise item.error

            yield from self._consume_ticks(item)

        final = self._flush()
        if final is not None:
            yield final

    def _consume_ticks(self, ticks: list[Candle]) -> Iterator[Candle]:
        for tick in ticks:
            if not self.config.session.is_market_open(tick.timestamp):
                continue
            candle = self._aggregator.add(tick)
            if candle is not None:
                yield self._prepare(candle)

    def _flush_if_elapsed(self) -> Candle | None:
        if not self._aggregator.has_elapsed(self._now()):
            return None
        return self._flush()

    def _flush(self) -> Candle | None:
        candle = self._aggregator.flush()
        return None if candle is None else self._prepare(candle)

    def _prepare(self, candle: Candle) -> Candle:
        """Validate an emitted candle and log the first one received.

        The aggregator only ever emits strictly increasing bucket starts, so
        duplicate timestamps are structurally impossible and single-candle
        validation is sufficient.
        """

        self._validator.validate([candle])
        if not self._first_candle_seen:
            self._first_candle_seen = True
            logger.info(
                "First candle received for %s at %s.", self.symbol, candle.timestamp
            )
        logger.debug("Candle emitted for %s at %s.", self.symbol, candle.timestamp)
        return candle

    def _market_has_closed(self) -> bool:
        """Return whether the session has *ended*, not merely whether we are outside it.

        Before the open the feed must idle and wait, not terminate: a paper or
        live session is realistically started before the bell, and treating
        "not yet open" as "closed" would end the run before the first tick.
        """

        if not self.config.stop_at_market_close:
            return False
        return self._now().time() > self.config.session.market_close

    def _start_drain(self) -> None:
        self._drain_thread = threading.Thread(
            target=self._drain, name=f"live-feed-{self.symbol}", daemon=True
        )
        self._drain_thread.start()

    def _drain(self) -> None:
        """Move ticks from the provider onto the queue, reconnecting as needed.

        Runs on the private drain thread. Reconnects deliberately leave the
        aggregator untouched, so a brief outage mid-candle resumes the same
        bucket instead of discarding partial data.
        """

        attempt = 0
        while not self._stop_requested.is_set():
            try:
                for ticks in self._provider.stream_ticks([self.symbol]):
                    if self._stop_requested.is_set():
                        break
                    attempt = 0
                    self._queue.put(ticks)
                break
            except Exception as error:
                attempt += 1
                if attempt > self.config.max_reconnect_attempts:
                    logger.error(
                        "Live feed for %s exhausted %d reconnect attempts.",
                        self.symbol,
                        self.config.max_reconnect_attempts,
                    )
                    self._queue.put(_FeedFailure(error))
                    return
                delay = self._backoff_for(attempt)
                logger.warning(
                    "Live feed for %s disconnected (%s); reconnect attempt %d in %.1fs.",
                    self.symbol,
                    error,
                    attempt,
                    delay,
                )
                if self._stop_requested.wait(timeout=delay):
                    break

        self._queue.put(_SENTINEL)

    def _backoff_for(self, attempt: int) -> float:
        delay = self.config.reconnect_backoff_seconds * (2 ** (attempt - 1))
        return min(delay, self.config.max_reconnect_backoff_seconds)

    def _cleanup_drain(self) -> None:
        self._stop_requested.set()
        thread = self._drain_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.config.poll_timeout_seconds)
