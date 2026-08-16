"""Trade-level performance statistics not owned by a more specific module."""

from __future__ import annotations

from datetime import timedelta

from domain.trade_record import TradeRecord


def average_r_multiple(trades: list[TradeRecord]) -> float:
    """Average PnL expressed in multiples of each trade's initial risk.

    Trades with no recorded stop-loss are excluded rather than treated as
    zero, since an R-multiple is undefined without a risk basis to divide
    by.
    """

    r_multiples = []
    for trade in trades:
        if trade.stop_loss is None:
            continue
        risk_per_share = abs(trade.entry_price - trade.stop_loss)
        if risk_per_share <= 0:
            continue
        initial_risk = risk_per_share * trade.quantity
        r_multiples.append(trade.pnl / initial_risk)

    return sum(r_multiples) / len(r_multiples) if r_multiples else 0.0


def consecutive_wins_losses(trades: list[TradeRecord]) -> tuple[int, int]:
    """Return (longest winning streak, longest losing streak) in close order."""

    longest_win_streak = 0
    longest_loss_streak = 0
    current_win_streak = 0
    current_loss_streak = 0

    for trade in trades:
        if trade.pnl > 0:
            current_win_streak += 1
            current_loss_streak = 0
        elif trade.pnl < 0:
            current_loss_streak += 1
            current_win_streak = 0
        else:
            current_win_streak = 0
            current_loss_streak = 0

        longest_win_streak = max(longest_win_streak, current_win_streak)
        longest_loss_streak = max(longest_loss_streak, current_loss_streak)

    return longest_win_streak, longest_loss_streak


def average_trade_duration(trades: list[TradeRecord]) -> timedelta:
    """Average wall-clock holding time across trades."""

    if not trades:
        return timedelta(0)
    total = sum((trade.exit_time - trade.entry_time for trade in trades), timedelta(0))
    return total / len(trades)


def exposure_pct(trades: list[TradeRecord], total_session_minutes: float) -> float:
    """Fraction of available session time spent with a position open.

    ``total_session_minutes`` is the caller's responsibility (e.g. trading
    days in the backtest window times minutes per session): trades alone
    don't know how much time the market was even open, so this function
    can't derive it on its own.
    """

    if total_session_minutes <= 0:
        return 0.0

    held_minutes = sum(
        (trade.exit_time - trade.entry_time).total_seconds() / 60.0 for trade in trades
    )
    return held_minutes / total_session_minutes
