"""Average True Range indicator (Wilder's smoothing)."""

from __future__ import annotations

from domain.candle import Candle
from indicators.base import Indicator


class ATR(Indicator):
    """Incremental Average True Range using Wilder's smoothing method.

    The first ``period`` true ranges are averaged with a simple mean to seed
    the indicator; every true range after that is folded in with Wilder's
    smoothing (``((period - 1) * previous_atr + true_range) / period``),
    matching the standard ATR definition used by every charting platform.
    """

    def __init__(self, period: int = 14) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self.reset()

    def update(self, candle: Candle) -> None:
        """Update ATR state with one candle's true range."""

        true_range = self._true_range(candle)

        if self._value is None:
            self._seed_true_ranges.append(true_range)
            if len(self._seed_true_ranges) == self.period:
                self._value = sum(self._seed_true_ranges) / self.period
        else:
            self._value = (
                (self.period - 1) * self._value + true_range
            ) / self.period

        self._previous_close = candle.close

    def reset(self) -> None:
        """Clear ATR state for a new session or calculation window."""

        self._previous_close: float | None = None
        self._seed_true_ranges: list[float] = []
        self._value: float | None = None

    @property
    def ready(self) -> bool:
        """Return whether ATR has completed its seeding window."""

        return self._value is not None

    @property
    def value(self) -> float | None:
        """Return the current ATR value."""

        return self._value

    def _true_range(self, candle: Candle) -> float:
        if self._previous_close is None:
            return candle.high - candle.low

        return max(
            candle.high - candle.low,
            abs(candle.high - self._previous_close),
            abs(candle.low - self._previous_close),
        )
