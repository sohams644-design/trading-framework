"""Risk-gate decision domain model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RejectReason(Enum):
    """Structured reasons a risk gate can reject a signal."""

    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_TRADES = "MAX_TRADES"
    INVALID_SIGNAL = "INVALID_SIGNAL"
    INSUFFICIENT_CAPITAL = "INSUFFICIENT_CAPITAL"
    POSITION_LIMIT = "POSITION_LIMIT"
    POSITION_ALREADY_OPEN = "POSITION_ALREADY_OPEN"
    MARKET_CLOSED = "MARKET_CLOSED"
    SAFETY_CHECK_FAILED = "SAFETY_CHECK_FAILED"


# A rule check reports the reason it rejected a signal, plus a human-readable
# detail for logging; passing checks return None instead of this tuple.
RiskCheckResult = tuple[RejectReason, str] | None


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """The outcome of evaluating a signal against the risk gate."""

    approved: bool
    quantity: int
    reason: RejectReason | None = None
    message: str | None = None

    @classmethod
    def approved_entry(cls, quantity: int, message: str | None = None) -> "RiskDecision":
        """Approve an entry signal with a sized quantity."""

        return cls(approved=True, quantity=quantity, message=message)

    @classmethod
    def approved_exit(cls, message: str | None = None) -> "RiskDecision":
        """Approve an exit signal unconditionally.

        Risk never blocks exits and never sizes them; the portfolio determines
        how many shares to close.
        """

        return cls(
            approved=True,
            quantity=0,
            message=message or "Exit signals bypass risk gating.",
        )

    @classmethod
    def rejected(cls, reason: RejectReason, message: str | None = None) -> "RiskDecision":
        """Reject a signal with a structured reason."""

        return cls(approved=False, quantity=0, reason=reason, message=message)
