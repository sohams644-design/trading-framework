from datetime import datetime

from domain.trade import TradeDirection
from domain.trade_record import TradeRecord
from performance.drawdown import max_drawdown
from performance.expectancy import average_loser, average_winner, profit_factor, win_rate


def _trade(pnl: float) -> TradeRecord:
    return TradeRecord(
        symbol="RELIANCE",
        direction=TradeDirection.BUY,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        quantity=1,
        pnl=pnl,
        entry_time=datetime(2026, 7, 30, 9, 30),
        exit_time=datetime(2026, 7, 30, 10, 0),
    )


def test_win_rate_with_no_trades_is_zero():
    assert win_rate([]) == 0.0


def test_win_rate_computes_fraction_of_winners():
    trades = [_trade(10), _trade(-5), _trade(20), _trade(-1)]

    assert win_rate(trades) == 0.5


def test_average_winner_and_loser_with_no_trades_is_zero():
    assert average_winner([]) == 0.0
    assert average_loser([]) == 0.0


def test_average_winner_and_loser_compute_correct_means():
    trades = [_trade(10), _trade(30), _trade(-4), _trade(-8)]

    assert average_winner(trades) == 20.0
    assert average_loser(trades) == -6.0


def test_profit_factor_with_no_trades_is_zero():
    assert profit_factor([]) == 0.0


def test_profit_factor_computes_gross_profit_over_gross_loss():
    trades = [_trade(100), _trade(-50)]

    assert profit_factor(trades) == 2.0


def test_profit_factor_is_infinite_with_no_losses():
    trades = [_trade(10), _trade(20)]

    assert profit_factor(trades) == float("inf")


def test_max_drawdown_with_no_trades_is_zero():
    assert max_drawdown([]) == 0.0


def test_max_drawdown_tracks_largest_peak_to_trough_drop():
    # Cumulative PnL walks: 100 -> 150 -> 90 -> 110 -> 40
    # Peak 150 to trough 40 is the worst drawdown of 110.
    trades = [_trade(100), _trade(50), _trade(-60), _trade(20), _trade(-70)]

    assert max_drawdown(trades) == 110.0
