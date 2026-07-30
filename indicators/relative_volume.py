"""Relative volume indicator."""

from __future__ import annotations

from collections import deque

from domain.candle import Candle
from indicators.base import Indicator


class RelativeVolume(Indicator):
    """Compares current candle volume with a rolling average."""

    def __init__(self, lookback_period: int = 20) -> None:
        if lookback_period <= 0:
            raise ValueError("lookback_period must be positive")
        self.lookback_period = lookback_period
        self.reset()

    def update(self, candle: Candle) -> None:
        """Update relative volume from one candle."""

        self._current_volume_ratio = None
        if len(self._volumes) == self.lookback_period:
            average_volume = sum(self._volumes) / self.lookback_period
            if average_volume > 0:
                self._current_volume_ratio = candle.volume / average_volume

        self._volumes.append(candle.volume)

    def reset(self) -> None:
        """Clear rolling volume history."""

        self._volumes: deque[int] = deque(maxlen=self.lookback_period)
        self._current_volume_ratio: float | None = None

    @property
    def ready(self) -> bool:
        """Return whether a current relative-volume value is available."""

        return self._current_volume_ratio is not None

    @property
    def current_volume_ratio(self) -> float | None:
        """Return current volume divided by rolling average volume."""

        return self._current_volume_ratio
