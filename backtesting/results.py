"""Aggregates a completed backtest's TradeLog into summary statistics."""

from __future__ import annotations

from dataclasses import dataclass

from performance.drawdown import max_drawdown
from performance.expectancy import average_loser, average_winner, profit_factor, win_rate
from portfolio.trade_log import TradeLog


@dataclass(frozen=True, slots=True)
class BacktestResults:
    """The basic summary statistics for one completed backtest run."""

    trade_count: int
    win_rate: float
    net_pnl: float
    average_winner: float
    average_loser: float
    profit_factor: float
    max_drawdown: float


class Results:
    """Builds BacktestResults from a completed run's TradeLog.

    This is a thin adapter: the actual statistics are computed by
    ``performance/``, not duplicated here.
    """

    def calculate(self, trade_log: TradeLog) -> BacktestResults:
        """Compute summary statistics from a trade log."""

        trades = trade_log.records
        return BacktestResults(
            trade_count=len(trades),
            win_rate=win_rate(trades),
            net_pnl=sum(trade.pnl for trade in trades),
            average_winner=average_winner(trades),
            average_loser=average_loser(trades),
            profit_factor=profit_factor(trades),
            max_drawdown=max_drawdown(trades),
        )
