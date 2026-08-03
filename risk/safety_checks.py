"""Session- and symbol-level safety gating for entry signals."""

from __future__ import annotations

from config.risk import RiskConfig
from domain.risk_decision import RejectReason, RiskCheckResult
from domain.signal import Signal
from risk.risk_context import RiskContext


class SafetyChecks:
    """Evaluates whether an entry signal is even eligible for sizing.

    Each check is independent of any broker: it only reasons about the
    signal, the current ``RiskContext``, and the configured ``RiskConfig``.
    """

    def evaluate(
        self,
        signal: Signal,
        context: RiskContext,
        config: RiskConfig,
    ) -> RiskCheckResult:
        """Return the first failing safety check, or None if all pass."""

        if not context.market_open:
            return RejectReason.MARKET_CLOSED, "Market is currently closed."

        if not context.trading_enabled:
            return RejectReason.SAFETY_CHECK_FAILED, "Trading is currently disabled."

        if config.allowed_symbols is not None and signal.symbol not in config.allowed_symbols:
            return (
                RejectReason.SAFETY_CHECK_FAILED,
                f"{signal.symbol} is not in the allowed symbol list.",
            )

        if signal.symbol in context.active_symbols:
            return (
                RejectReason.POSITION_ALREADY_OPEN,
                f"Already have an active position or order in {signal.symbol}.",
            )

        return None
