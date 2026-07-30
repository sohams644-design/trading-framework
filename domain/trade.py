from dataclasses import dataclass
from enum import Enum


class TradeDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class Trade:
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    target: float
    quantity: int
    status: TradeStatus = TradeStatus.PENDING