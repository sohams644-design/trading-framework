"""Position domain model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Position:
    """Represents an open net position for a symbol."""

    symbol: str
    quantity: int
    average_price: float
