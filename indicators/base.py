"""Base lifecycle for all indicators."""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.candle import Candle


class Indicator(ABC):
    """Abstract base class for incremental indicators."""

    @abstractmethod
    def update(self, candle: Candle) -> None:
        """Update indicator state with one candle."""
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        """Reset indicator state for a new session or calculation window."""
        raise NotImplementedError

    @property
    @abstractmethod
    def ready(self) -> bool:
        """Return whether the indicator has enough data for consumption."""
        raise NotImplementedError
