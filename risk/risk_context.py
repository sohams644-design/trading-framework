"""Runtime context the risk gate evaluates signals against."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RiskContext:
    """A snapshot of account and session state used to gate a signal.

    Unlike ``RiskConfig`` (static thresholds), this changes throughout the
    trading day as trades are taken and positions open and close.
    """

    capital: float
    capital_deployed: float = 0.0
    daily_realized_loss: float = 0.0
    trades_today: int = 0
    open_positions: int = 0
    active_symbols: set[str] = field(default_factory=set)
    market_open: bool = True
    trading_enabled: bool = True
