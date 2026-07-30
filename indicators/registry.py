"""Indicator registry for named indicator instances."""

from __future__ import annotations

from indicators.base import Indicator


class IndicatorRegistry:
    """Stores indicator instances by name."""

    def __init__(self) -> None:
        self._indicators: dict[str, Indicator] = {}

    def register(self, name: str, indicator: Indicator) -> None:
        """Register an indicator by name."""

        normalized_name = name.lower()
        if normalized_name in self._indicators:
            raise ValueError(f"Indicator already registered: {normalized_name}")
        self._indicators[normalized_name] = indicator

    def get(self, name: str) -> Indicator:
        """Return a registered indicator by name."""

        normalized_name = name.lower()
        try:
            return self._indicators[normalized_name]
        except KeyError as exc:
            raise KeyError(f"Indicator not registered: {normalized_name}") from exc

    def all(self) -> tuple[Indicator, ...]:
        """Return all registered indicators in registration order."""

        return tuple(self._indicators.values())

    def reset(self) -> None:
        """Reset every registered indicator."""

        for indicator in self._indicators.values():
            indicator.reset()
