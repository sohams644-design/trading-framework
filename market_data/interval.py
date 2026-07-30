"""Typed market-data intervals supported by the framework."""

from __future__ import annotations

from enum import Enum


class Interval(Enum):
    """Historical candle intervals accepted by market-data providers."""

    ONE_MINUTE = "minute"
    THREE_MINUTE = "3minute"
    FIVE_MINUTE = "5minute"
    FIFTEEN_MINUTE = "15minute"
    DAY = "day"

    @classmethod
    def from_value(cls, value: str) -> "Interval":
        """Create an interval from its provider value."""

        for interval in cls:
            if interval.value == value:
                return interval
        raise ValueError(f"Unsupported interval: {value}")
