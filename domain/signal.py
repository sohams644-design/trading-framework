"""Trading signal domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SignalAction(Enum):
    """Supported signal decisions emitted by strategies."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"


@dataclass(frozen=True, slots=True)
class Signal:
    """Represents a strategy recommendation at a point in time."""

    symbol: str
    action: SignalAction
    timestamp: datetime
    price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    quantity: int | None = None
    confidence: float | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def buy(
        cls,
        symbol: str,
        timestamp: datetime,
        price: float | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Signal":
        """Create a long-entry signal."""

        return cls._build(symbol, SignalAction.BUY, timestamp, price, reason, metadata)

    @classmethod
    def sell(
        cls,
        symbol: str,
        timestamp: datetime,
        price: float | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Signal":
        """Create a short-entry signal."""

        return cls._build(symbol, SignalAction.SELL, timestamp, price, reason, metadata)

    @classmethod
    def none(
        cls,
        symbol: str,
        timestamp: datetime,
        price: float | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Signal":
        """Create a no-trade signal."""

        return cls._build(symbol, SignalAction.HOLD, timestamp, price, reason, metadata)

    @classmethod
    def exit_long(
        cls,
        symbol: str,
        timestamp: datetime,
        price: float | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Signal":
        """Create a long-position exit signal."""

        return cls._build(
            symbol, SignalAction.EXIT_LONG, timestamp, price, reason, metadata
        )

    @classmethod
    def exit_short(
        cls,
        symbol: str,
        timestamp: datetime,
        price: float | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Signal":
        """Create a short-position exit signal."""

        return cls._build(
            symbol, SignalAction.EXIT_SHORT, timestamp, price, reason, metadata
        )

    @property
    def is_entry(self) -> bool:
        """Return whether the signal opens a directional position."""

        return self.action in {SignalAction.BUY, SignalAction.SELL}

    @property
    def is_exit(self) -> bool:
        """Return whether the signal exits an open position."""

        return self.action in {SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT}

    @staticmethod
    def _build(
        symbol: str,
        action: SignalAction,
        timestamp: datetime,
        price: float | None,
        reason: str | None,
        metadata: dict[str, Any] | None,
    ) -> "Signal":
        return Signal(
            symbol=symbol.upper(),
            action=action,
            timestamp=timestamp,
            price=price,
            reason=reason,
            metadata=metadata or {},
        )
