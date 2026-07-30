"""Opening range indicator."""

from __future__ import annotations

from dataclasses import dataclass

from domain.candle import Candle
from indicators.base import Indicator
from indicators.session import MarketSession


@dataclass(slots=True)
class OpeningRange(Indicator):
    """Tracks opening high/low and post-range breakout state."""

    session: MarketSession = MarketSession()

    def __post_init__(self) -> None:
        self.reset()

    def update(self, candle: Candle) -> None:
        """Update opening range state with one candle."""

        if self.session.is_opening_range_active(candle.timestamp):
            self._update_range(candle)
            return

        if self.session.is_opening_range_complete(candle.timestamp):
            self._range_complete = self.opening_high is not None and self.opening_low is not None
            self._update_breakout_state(candle)

    def reset(self) -> None:
        """Clear opening range and breakout state."""

        self.opening_high: float | None = None
        self.opening_low: float | None = None
        self._range_complete = False
        self.breakout_above = False
        self.breakout_below = False

    @property
    def ready(self) -> bool:
        """Return whether the opening range has completed."""

        return self._range_complete

    @property
    def range_complete(self) -> bool:
        """Return whether the opening range has completed."""

        return self._range_complete

    def _update_range(self, candle: Candle) -> None:
        self.opening_high = candle.high if self.opening_high is None else max(
            self.opening_high, candle.high
        )
        self.opening_low = candle.low if self.opening_low is None else min(
            self.opening_low, candle.low
        )

    def _update_breakout_state(self, candle: Candle) -> None:
        if self.opening_high is None or self.opening_low is None:
            return
        self.breakout_above = candle.high > self.opening_high
        self.breakout_below = candle.low < self.opening_low
