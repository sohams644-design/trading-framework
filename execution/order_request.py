"""Broker-independent order request contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from domain.trade import TradeDirection


class OrderType(Enum):
    """Supported order types accepted by execution providers."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "SL"
    STOP_LOSS_MARKET = "SL-M"


class Product(Enum):
    """Supported margin/settlement products accepted by execution providers."""

    INTRADAY = "MIS"
    DELIVERY = "CNC"
    NORMAL = "NRML"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """Immutable, broker-independent description of an order to place."""

    symbol: str
    exchange: str
    side: TradeDirection
    quantity: int
    order_type: OrderType
    product: Product
    price: float | None = None
    trigger_price: float | None = None
    tag: str | None = None
