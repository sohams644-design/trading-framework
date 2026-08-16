"""Risk-adjusted return ratios computed from a daily-aggregated PnL series."""

from __future__ import annotations

import math
from collections import defaultdict

from domain.trade_record import TradeRecord

_TRADING_DAYS_PER_YEAR = 252


def _daily_pnl(trades: list[TradeRecord]) -> list[float]:
    """Aggregate trade PnL into one realized-PnL figure per calendar day.

    Sharpe/Sortino/Calmar are return-series statistics. A per-trade PnL
    series over-counts volatility on multi-trade days and under-counts it on
    quiet ones, so every ratio here is computed off daily, not per-trade,
    PnL. With only a handful of trading days (a one-month backtest is
    ~21 days), these ratios are statistically noisy almost by definition --
    that's a property of the sample size, not of this implementation.
    """

    by_day: dict = defaultdict(float)
    for trade in trades:
        by_day[trade.exit_time.date()] += trade.pnl
    return [by_day[day] for day in sorted(by_day)]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _downside_stdev(values: list[float], target: float = 0.0) -> float:
    downside = [min(v - target, 0.0) for v in values]
    if len(downside) < 2:
        return 0.0
    variance = sum(d ** 2 for d in downside) / (len(downside) - 1)
    return math.sqrt(variance)


def sharpe_ratio(trades: list[TradeRecord], risk_free_daily: float = 0.0) -> float:
    """Annualized Sharpe ratio from daily realized PnL.

    Returns 0.0 when there's fewer than two trading days, or zero variance,
    to divide by -- rather than raising, since an empty/short backtest is a
    normal input, not an error.
    """

    daily = _daily_pnl(trades)
    if len(daily) < 2:
        return 0.0

    excess = [pnl - risk_free_daily for pnl in daily]
    stdev = _stdev(excess)
    if stdev == 0:
        return 0.0
    return (_mean(excess) / stdev) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def sortino_ratio(trades: list[TradeRecord], risk_free_daily: float = 0.0) -> float:
    """Annualized Sortino ratio: like Sharpe, but only penalizes downside variance."""

    daily = _daily_pnl(trades)
    if len(daily) < 2:
        return 0.0

    excess = [pnl - risk_free_daily for pnl in daily]
    downside = _downside_stdev(excess)
    if downside == 0:
        return 0.0
    return (_mean(excess) / downside) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def calmar_ratio(trades: list[TradeRecord], max_drawdown: float) -> float:
    """Annualized realized PnL divided by max drawdown.

    ``max_drawdown`` is passed in rather than recomputed here, since
    ``performance.drawdown.max_drawdown`` already owns that calculation --
    this keeps one definition of drawdown instead of two.
    """

    daily = _daily_pnl(trades)
    if not daily or max_drawdown <= 0:
        return 0.0

    total_pnl = sum(daily)
    annualized_pnl = total_pnl / len(daily) * _TRADING_DAYS_PER_YEAR
    return annualized_pnl / max_drawdown
