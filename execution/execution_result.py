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
    """Outcome of an execution-provider operation on an order."""

    success: bool
    status: OrderStatus
    timestamp: datetime
    broker_order_id: str | None = None
    message: str | None = None
