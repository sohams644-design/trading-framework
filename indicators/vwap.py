"""Incremental VWAP indicator."""

from __future__ import annotations

from domain.candle import Candle
from indicators.base import Indicator


class VWAP(Indicator):
    """Volume-weighted average price calculated incrementally."""

    def __init__(self) -> None:
        self.reset()

    def update(self, candle: Candle) -> None:
        """Add one candle to the VWAP calculation."""

        if candle.volume <= 0:
            return

        typical_price = (candle.high + candle.low + candle.close) / 3
        self._cumulative_price_volume += typical_price * candle.volume
        self._cumulative_volume += candle.volume

    def reset(self) -> None:
        """Clear cumulative VWAP state."""

        self._cumulative_price_volume = 0.0
        self._cumulative_volume = 0

    @property
    def ready(self) -> bool:
        """Return whether VWAP has at least one positive-volume candle."""

        return self._cumulative_volume > 0

    @property
    def value(self) -> float | None:
        """Return the current VWAP value."""

        if not self.ready:
            return None
        return self._cumulative_price_volume / self._cumulative_volume
