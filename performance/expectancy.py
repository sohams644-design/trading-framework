"""Win-rate and profit-factor statistics over completed trades."""

from __future__ import annotations

from domain.trade_record import TradeRecord


def win_rate(trades: list[TradeRecord]) -> float:
    """Return the fraction of trades with positive PnL."""

    if not trades:
        return 0.0
    wins = sum(1 for trade in trades if trade.pnl > 0)
    return wins / len(trades)


def average_winner(trades: list[TradeRecord]) -> float:
    """Return the average PnL of winning trades, or 0.0 if there are none."""

    winners = [trade.pnl for trade in trades if trade.pnl > 0]
    return sum(winners) / len(winners) if winners else 0.0


def average_loser(trades: list[TradeRecord]) -> float:
    """Return the average PnL of losing trades, or 0.0 if there are none."""

    losers = [trade.pnl for trade in trades if trade.pnl < 0]
    return sum(losers) / len(losers) if losers else 0.0


def profit_factor(trades: list[TradeRecord]) -> float:
    """Return gross profit divided by gross loss.

    Returns ``float("inf")`` when there are winning trades and no losses, and
    ``0.0`` when there is no data to compute a ratio from.
    """

    gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
    gross_loss = sum(-trade.pnl for trade in trades if trade.pnl < 0)

    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def expectancy(trades: list[TradeRecord]) -> float:
    """Return the expected PnL of the next trade, in rupees.

    ``win_rate * average_winner + (1 - win_rate) * average_loser``.
    ``average_loser`` is already negative, so this is a signed sum, not a
    difference. A negative expectancy means the system loses money on
    average per trade regardless of how good any individual win looks.
    """

    if not trades:
        return 0.0

    rate = win_rate(trades)
    return rate * average_winner(trades) + (1 - rate) * average_loser(trades)
