"""Aggregates raw ticks into interval candles."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from domain.candle import Candle
from indicators.session import MarketSession
from market_data.interval import Interval

logger = logging.getLogger(__name__)

_INTERVAL_MINUTES: dict[Interval, int] = {
    Interval.ONE_MINUTE: 1,
    Interval.THREE_MINUTE: 3,
    Interval.FIVE_MINUTE: 5,
    Interval.FIFTEEN_MINUTE: 15,
}


class TickAggregator:
    """Builds interval candles from a stream of ticks.

    Ticks arrive as degenerate candles (open=high=low=close=last price) whose
    ``volume`` carries the broker's *cumulative* day volume. This class turns
    them into real bars: bucket-aligned timestamps, true OHLC, and per-bucket
    volume computed as a delta of the cumulative figure.

    It is entirely broker-independent and holds no connection state.
    """

    def __init__(
        self,
        interval: Interval = Interval.ONE_MINUTE,
        session: MarketSession | None = None,
    ) -> None:
        if interval not in _INTERVAL_MINUTES:
            raise ValueError(f"Interval not supported for tick aggregation: {interval}")
        self.interval = interval
        self.session = session or MarketSession()
        self._delta = timedelta(minutes=_INTERVAL_MINUTES[interval])
        self.reset()

    def reset(self) -> None:
        """Clear all bucket state, for a new session."""

        self._bucket_start: datetime | None = None
        self._open = 0.0
        self._high = 0.0
        self._low = 0.0
        self._close = 0.0
        self._baseline_volume = 0
        self._latest_volume = 0
        self._session_volume: int | None = None
        self._last_emitted_bucket: datetime | None = None

    @property
    def has_open_bucket(self) -> bool:
        """Return whether a partially built candle is currently open."""

        return self._bucket_start is not None

    @property
    def current_bucket_start(self) -> datetime | None:
        """Return the start timestamp of the open bucket, if any."""

        return self._bucket_start

    def has_elapsed(self, now: datetime) -> bool:
        """Return whether the open bucket's interval has already passed."""

        if self._bucket_start is None:
            return False
        return now >= self._bucket_start + self._delta

    def add(self, tick: Candle) -> Candle | None:
        """Add one tick, returning a completed candle when a bucket rolls over."""

        bucket_start = self._bucket_start_for(tick.timestamp)

        if self._last_emitted_bucket is not None and bucket_start <= self._last_emitted_bucket:
            logger.warning(
                "Dropping late tick at %s for already-emitted bucket %s.",
                tick.timestamp,
                bucket_start,
            )
            return None

        if self._bucket_start is None:
            self._open_bucket(bucket_start, tick)
            return None

        if bucket_start == self._bucket_start:
            self._update_bucket(tick)
            return None

        completed = self._build_candle()
        self._open_bucket(bucket_start, tick)
        return completed

    def flush(self) -> Candle | None:
        """Close and return the open bucket, if one exists."""

        if not self.has_open_bucket:
            return None
        return self._build_candle()

    def _bucket_start_for(self, timestamp: datetime) -> datetime:
        anchor = datetime.combine(
            timestamp.date(), self.session.market_open, tzinfo=timestamp.tzinfo
        )
        elapsed_seconds = (timestamp - anchor).total_seconds()
        buckets = math.floor(elapsed_seconds / self._delta.total_seconds())
        return anchor + buckets * self._delta

    def _open_bucket(self, bucket_start: datetime, tick: Candle) -> None:
        self._bucket_start = bucket_start
        self._open = tick.close
        self._high = tick.high
        self._low = tick.low
        self._close = tick.close
        self._baseline_volume = self._baseline_for(tick)
        self._latest_volume = tick.volume
        self._session_volume = tick.volume

    def _baseline_for(self, tick: Candle) -> int:
        """Return the cumulative volume this bucket should measure from.

        Normally that is the previous bucket's final cumulative volume, so no
        traded volume is lost between bars. For the first bucket after
        connecting there is no previous figure, so the tick's own cumulative
        value is used; that undercounts the first bar by a single tick, which
        beats treating a mid-session connect as if the whole day traded in
        one bar. A cumulative figure that moves backwards means the broker
        reset it (new day), so the baseline resets with it.
        """

        if self._session_volume is None or tick.volume < self._session_volume:
            return tick.volume
        return self._session_volume

    def _update_bucket(self, tick: Candle) -> None:
        self._high = max(self._high, tick.high)
        self._low = min(self._low, tick.low)
        self._close = tick.close
        if tick.volume >= self._latest_volume:
            self._latest_volume = tick.volume
        self._session_volume = self._latest_volume

    def _build_candle(self) -> Candle:
        candle = Candle(
            timestamp=self._bucket_start,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=max(0, self._latest_volume - self._baseline_volume),
        )
        self._last_emitted_bucket = self._bucket_start
        self._bucket_start = None
        return candle
