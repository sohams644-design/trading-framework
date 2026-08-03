"""Maximum drawdown calculation over a sequence of completed trades."""

from __future__ import annotations

from domain.trade_record import TradeRecord


def max_drawdown(trades: list[TradeRecord]) -> float:
    """Return the largest peak-to-trough drop in cumulative realized PnL.

    Trades are consumed in the order given, which should be close order (as
    ``TradeLog`` naturally maintains). This tracks realized PnL only, not a
    mark-to-market equity curve.
    """

    cumulative = 0.0
    peak = 0.0
    worst_drawdown = 0.0

    for trade in trades:
        cumulative += trade.pnl
        peak = max(peak, cumulative)
        worst_drawdown = max(worst_drawdown, peak - cumulative)

    return worst_drawdown
