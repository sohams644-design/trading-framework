"""Broker-independent execution outcome contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderStatus(Enum):
    """Lifecycle states an order can occupy, independent of broker vocabulary."""

    NEW = "NEW"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Outcome of an execution-provider operation on an order.

    ``fill_price`` is intentionally minimal: it only records the price a
    provider filled at. As fill data grows (filled quantity, partial fills,
    average price), a future version should extract fills into their own
    ``ExecutionFill`` object rather than keep expanding this one.
    """

    success: bool
    status: OrderStatus
    timestamp: datetime
    broker_order_id: str | None = None
    message: str | None = None
    fill_price: float | None = None
