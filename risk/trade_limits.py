"""Portfolio- and session-level exposure limits."""

from __future__ import annotations

from config.risk import RiskConfig
from domain.risk_decision import RejectReason, RiskCheckResult
from domain.signal import Signal
from risk.risk_context import RiskContext


class TradeLimits:
    """Evaluates portfolio-wide limits, independent of any single symbol."""

    def evaluate(
        self,
        signal: Signal,
        context: RiskContext,
        config: RiskConfig,
    ) -> RiskCheckResult:
        """Return the first breached limit, or None if all limits are respected."""

        del signal  # Limits below are portfolio-wide, not symbol-specific.

        if context.trades_today >= config.max_trades_per_day:
            return (
                RejectReason.MAX_TRADES,
                f"Reached the maximum of {config.max_trades_per_day} trades today.",
            )

        if context.open_positions >= config.max_concurrent_positions:
            return (
                RejectReason.POSITION_LIMIT,
                f"Reached the maximum of {config.max_concurrent_positions} "
                "concurrent positions.",
            )

        if context.daily_realized_loss >= config.daily_loss_limit:
            return (
                RejectReason.DAILY_LOSS_LIMIT,
                f"Daily realized loss of {context.daily_realized_loss} has reached "
                f"the limit of {config.daily_loss_limit}.",
            )

        if context.capital_deployed >= config.max_capital_exposure:
            return (
                RejectReason.INSUFFICIENT_CAPITAL,
                f"Deployed capital of {context.capital_deployed} has reached the "
                f"exposure limit of {config.max_capital_exposure}.",
            )

        return None
