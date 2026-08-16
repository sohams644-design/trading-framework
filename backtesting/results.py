"""Aggregates a completed backtest's TradeLog into summary statistics."""

from __future__ import annotations

from dataclasses import dataclass

from performance.drawdown import max_drawdown
from performance.expectancy import (
    average_loser,
    average_winner,
    expectancy,
    profit_factor,
    win_rate,
)
from performance.performance import (
    average_r_multiple,
    average_trade_duration,
    consecutive_wins_losses,
    exposure_pct,
)
from performance.sharpe import calmar_ratio, sharpe_ratio, sortino_ratio
from portfolio.trade_log import TradeLog


@dataclass(frozen=True, slots=True)
class BacktestResults:
    """Summary statistics for one completed backtest run."""

    trade_count: int
    win_rate: float
    net_pnl: float
    average_winner: float
    average_loser: float
    profit_factor: float
    max_drawdown: float
    expectancy: float = 0.0
    average_r_multiple: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    exposure_pct: float = 0.0
    average_trade_duration_minutes: float = 0.0
    average_mae: float = 0.0
    average_mfe: float = 0.0
    total_charges: float = 0.0


class Results:
    """Builds BacktestResults from a completed run's TradeLog.

    This is a thin adapter: the actual statistics are computed by
    ``performance/``, not duplicated here.
    """

    def calculate(
        self,
        trade_log: TradeLog,
        total_session_minutes: float | None = None,
    ) -> BacktestResults:
        """Compute summary statistics from a trade log.

        ``total_session_minutes`` is only needed for ``exposure_pct``: it's
        the total time the market was open across the backtest window
        (trading days * minutes per session), which a trade log alone
        can't derive. Omit it to leave ``exposure_pct`` at 0.0.
        """

        trades = trade_log.records
        drawdown = max_drawdown(trades)
        duration = average_trade_duration(trades)
        wins, losses = consecutive_wins_losses(trades)
        maes = [trade.mae for trade in trades if trade.mae is not None]
        mfes = [trade.mfe for trade in trades if trade.mfe is not None]

        return BacktestResults(
            trade_count=len(trades),
            win_rate=win_rate(trades),
            net_pnl=sum(trade.pnl for trade in trades),
            average_winner=average_winner(trades),
            average_loser=average_loser(trades),
            profit_factor=profit_factor(trades),
            max_drawdown=drawdown,
            expectancy=expectancy(trades),
            average_r_multiple=average_r_multiple(trades),
            sharpe_ratio=sharpe_ratio(trades),
            sortino_ratio=sortino_ratio(trades),
            calmar_ratio=calmar_ratio(trades, drawdown),
            max_consecutive_wins=wins,
            max_consecutive_losses=losses,
            exposure_pct=(
                exposure_pct(trades, total_session_minutes)
                if total_session_minutes
                else 0.0
            ),
            average_trade_duration_minutes=duration.total_seconds() / 60.0,
            average_mae=sum(maes) / len(maes) if maes else 0.0,
            average_mfe=sum(mfes) / len(mfes) if mfes else 0.0,
            total_charges=sum(trade.charges for trade in trades),
        )
