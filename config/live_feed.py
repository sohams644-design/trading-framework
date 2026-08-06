"""Live market feed configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from indicators.session import MarketSession
from market_data.interval import Interval


@dataclass(frozen=True, slots=True)
class LiveFeedConfig:
    """Configurable behaviour for a live market feed.

    ``poll_timeout_seconds`` is how long the feed waits for new ticks before
    checking whether the open candle should be flushed or the session has
    closed. It is a responsiveness knob, not a trading parameter.
    """

    interval: Interval = Interval.ONE_MINUTE
    session: MarketSession = field(default_factory=MarketSession)
    max_reconnect_attempts: int = 5
    reconnect_backoff_seconds: float = 1.0
    max_reconnect_backoff_seconds: float = 30.0
    poll_timeout_seconds: float = 1.0
    stop_at_market_close: bool = True
