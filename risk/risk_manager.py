"""Orchestrates risk gating: coordinates rules, contains none of its own."""

from __future__ import annotations

from config.risk import RiskConfig
from domain.risk_decision import RejectReason, RiskDecision
from domain.signal import Signal
from risk.position_sizer import PositionSizer
from risk.risk_context import RiskContext
from risk.safety_checks import SafetyChecks
from risk.trade_limits import TradeLimits


class RiskManager:
    """Turns a Signal into a RiskDecision by coordinating risk components."""

    def __init__(
        self,
        config: RiskConfig | None = None,
        safety_checks: SafetyChecks | None = None,
        trade_limits: TradeLimits | None = None,
        position_sizer: PositionSizer | None = None,
    ) -> None:
        self.config = config or RiskConfig()
        self.safety_checks = safety_checks or SafetyChecks()
        self.trade_limits = trade_limits or TradeLimits()
        self.position_sizer = position_sizer or PositionSizer()

    def evaluate(self, signal: Signal, context: RiskContext) -> RiskDecision:
        """Gate a signal, approving exits unconditionally and sizing entries."""

        if signal.is_exit:
            return RiskDecision.approved_exit()

        if not signal.is_entry or signal.price is None:
            return RiskDecision.rejected(
                RejectReason.INVALID_SIGNAL,
                "Signal is not an actionable entry.",
            )

        safety_result = self.safety_checks.evaluate(signal, context, self.config)
        if safety_result is not None:
            reason, message = safety_result
            return RiskDecision.rejected(reason, message)

        limits_result = self.trade_limits.evaluate(signal, context, self.config)
        if limits_result is not None:
            reason, message = limits_result
            return RiskDecision.rejected(reason, message)

        quantity = self.position_sizer.calculate_quantity(
            context.capital, signal.price, self.config.capital_allocation_pct
        )
        if quantity <= 0:
            return RiskDecision.rejected(
                RejectReason.INSUFFICIENT_CAPITAL,
                "Computed position size is zero for the available capital.",
            )

        return RiskDecision.approved_entry(quantity)
