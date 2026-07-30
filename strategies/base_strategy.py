"""Base strategy interface for all trading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.candle import Candle
from domain.signal import Signal
from indicators.context import IndicatorContext


class BaseStrategy(ABC):
    """Abstract interface that every strategy implementation must follow."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol.upper()

    @abstractmethod
    def generate_signal(self, candle: Candle, context: IndicatorContext) -> Signal:
        """Generate a trading signal from the latest candle and indicators."""
        raise NotImplementedError
