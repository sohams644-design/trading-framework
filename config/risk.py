"""Risk management configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """Configurable thresholds enforced by the risk gate.

    ``capital_allocation_pct`` sizes a trade as a fraction of total capital.
    This is a capital-allocation limit, not an account-risk limit: without a
    stop-loss there is no basis for true risk-per-trade sizing yet. A future
    sprint can add a separate stop-loss-aware ``risk_per_trade_pct`` once
    stop-loss data is available to the sizer.
    """

    max_trades_per_day: int = 10
    max_concurrent_positions: int = 3
    daily_loss_limit: float = 5000.0
    max_capital_exposure: float = 100_000.0
    capital_allocation_pct: float = 0.1
    allowed_symbols: frozenset[str] | None = None
