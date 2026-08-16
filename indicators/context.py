"""Indicator context that owns and updates indicators."""

from __future__ import annotations

from domain.candle import Candle
from indicators.atr import ATR
from indicators.base import Indicator
from indicators.opening_range import OpeningRange
from indicators.registry import IndicatorRegistry
from indicators.relative_volume import RelativeVolume
from indicators.vwap import VWAP


class IndicatorContext:
    """Owns indicators and applies candle updates to all of them."""

    def __init__(self, registry: IndicatorRegistry | None = None) -> None:
        self.registry = registry or IndicatorRegistry()

    @classmethod
    def with_defaults(cls) -> "IndicatorContext":
        """Create a context with standard framework indicators."""

        context = cls()
        context.register("vwap", VWAP())
        context.register("opening_range", OpeningRange())
        # lookback_period=20 (100 minutes on 5-minute candles) is too slow for
        # an opening-range strategy meant to act in the first hour: RVOL
        # would not even be ready until ~11:00, regardless of threshold. 6
        # bars (30 minutes) keeps RVOL relevant to the ORB entry window.
        context.register("relative_volume", RelativeVolume(lookback_period=6))
        context.register("atr", ATR(period=7))
        return context

    def register(self, name: str, indicator: Indicator) -> None:
        """Register an indicator with the context."""

        self.registry.register(name, indicator)

    def update(self, candle: Candle) -> None:
        """Update every registered indicator with one candle."""

        for indicator in self.registry.all():
            indicator.update(candle)

    def reset(self) -> None:
        """Reset every registered indicator."""

        self.registry.reset()

    def get(self, name: str) -> Indicator:
        """Retrieve a registered indicator by name."""

        return self.registry.get(name)

    @property
    def vwap(self) -> VWAP:
        """Return the registered VWAP indicator."""

        indicator = self.get("vwap")
        if not isinstance(indicator, VWAP):
            raise TypeError("Registered vwap indicator is not a VWAP")
        return indicator

    @property
    def opening_range(self) -> OpeningRange:
        """Return the registered OpeningRange indicator."""

        indicator = self.get("opening_range")
        if not isinstance(indicator, OpeningRange):
            raise TypeError("Registered opening_range indicator is not an OpeningRange")
        return indicator

    @property
    def relative_volume(self) -> RelativeVolume:
        """Return the registered RelativeVolume indicator."""

        indicator = self.get("relative_volume")
        if not isinstance(indicator, RelativeVolume):
            raise TypeError("Registered relative_volume indicator is not a RelativeVolume")
        return indicator

    @property
    def atr(self) -> ATR:
        """Return the registered ATR indicator."""

        indicator = self.get("atr")
        if not isinstance(indicator, ATR):
            raise TypeError("Registered atr indicator is not an ATR")
        return indicator
