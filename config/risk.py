"""Risk management configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """Configurable thresholds enforced by the risk gate.

    ``capital_allocation_pct`` sizes a trade as a fraction of total capital
    and is used only as a fallback when a signal carries no stop-loss.
    ``risk_per_trade_pct`` is the primary sizer: whenever a signal carries a
    stop-loss, position size is derived from how much account equity is
    allowed to be lost if the stop is hit, not from a fixed capital slice.
    """

    max_trades_per_day: int = 10
    max_concurrent_positions: int = 3
    daily_loss_limit: float = 5000.0
    max_capital_exposure: float = 100_000.0
    capital_allocation_pct: float = 0.1
    risk_per_trade_pct: float = 0.01
    allowed_symbols: frozenset[str] | None = None
