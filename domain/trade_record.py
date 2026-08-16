"""Completed trade domain model, shared by backtesting, paper, and live trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.trade import TradeDirection


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """An immutable record of one fully closed round-trip trade."""

    symbol: str
    direction: TradeDirection
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    entry_time: datetime
    exit_time: datetime
    reason: str | None = None
    charges: float = 0.0
    stop_loss: float | None = None
    mae: float | None = None
    mfe: float | None = None
