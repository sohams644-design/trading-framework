from datetime import datetime, timedelta

import pytest

from domain.trade import TradeDirection
from domain.trade_record import TradeRecord
from performance.expectancy import average_loser, average_winner, expectancy, win_rate
from performance.performance import (
    average_r_multiple,
    average_trade_duration,
    consecutive_wins_losses,
    exposure_pct,
)
from performance.sharpe import calmar_ratio, sharpe_ratio, sortino_ratio


def _trade(
    pnl: float,
    day: int = 30,
    entry_hour: int = 9,
    entry_minute: int = 30,
    duration_minutes: int = 30,
    stop_loss: float | None = None,
    entry_price: float = 100.0,
    quantity: int = 1,
) -> TradeRecord:
    entry_time = datetime(2026, 7, day, entry_hour, entry_minute)
    return TradeRecord(
        symbol="RELIANCE",
        direction=TradeDirection.BUY,
        entry_price=entry_price,
        exit_price=entry_price + pnl / quantity,
        quantity=quantity,
        pnl=pnl,
        entry_time=entry_time,
        exit_time=entry_time + timedelta(minutes=duration_minutes),
        stop_loss=stop_loss,
    )


# --- expectancy ---


def test_expectancy_with_no_trades_is_zero():
    assert expectancy([]) == 0.0


def test_expectancy_combines_win_rate_and_average_win_loss():
    trades = [_trade(100.0), _trade(-40.0)]

    assert expectancy(trades) == pytest.approx(
        win_rate(trades) * average_winner(trades) + (1 - win_rate(trades)) * average_loser(trades)
    )
    assert expectancy(trades) == pytest.approx(30.0)


def test_expectancy_is_negative_for_a_losing_system():
    # 1 small win, 3 losses of the same size -- net loser despite each loss
    # being no worse than the win.
    trades = [_trade(10.0), _trade(-10.0), _trade(-10.0), _trade(-10.0)]

    assert expectancy(trades) < 0


# --- average_r_multiple ---


def test_average_r_multiple_with_no_trades_is_zero():
    assert average_r_multiple([]) == 0.0


def test_average_r_multiple_excludes_trades_without_a_stop_loss():
    trades = [_trade(100.0, stop_loss=None)]

    assert average_r_multiple(trades) == 0.0


def test_average_r_multiple_computes_pnl_over_initial_risk():
    # entry 100, stop 95 -> risk 5/share * 2 shares = 10 initial risk.
    # pnl 20 -> 2R.
    trade = _trade(20.0, entry_price=100.0, stop_loss=95.0, quantity=2)

    assert average_r_multiple([trade]) == pytest.approx(2.0)


def test_average_r_multiple_averages_across_trades_with_and_without_stops():
    two_r = _trade(20.0, entry_price=100.0, stop_loss=95.0, quantity=2)  # 2R
    no_stop = _trade(1000.0, stop_loss=None)  # excluded entirely

    assert average_r_multiple([two_r, no_stop]) == pytest.approx(2.0)


# --- consecutive_wins_losses ---


def test_consecutive_wins_losses_with_no_trades_is_zero_zero():
    assert consecutive_wins_losses([]) == (0, 0)


def test_consecutive_wins_losses_tracks_longest_streaks_in_close_order():
    trades = [
        _trade(10.0),   # W
        _trade(20.0),   # W
        _trade(-5.0),   # L
        _trade(30.0),   # W
        _trade(-1.0),   # L
        _trade(-2.0),   # L
        _trade(-3.0),   # L
    ]

    assert consecutive_wins_losses(trades) == (2, 3)


def test_consecutive_wins_losses_breakeven_trade_resets_both_streaks():
    trades = [_trade(10.0), _trade(0.0), _trade(20.0)]

    assert consecutive_wins_losses(trades) == (1, 0)


# --- average_trade_duration ---


def test_average_trade_duration_with_no_trades_is_zero():
    assert average_trade_duration([]) == timedelta(0)


def test_average_trade_duration_averages_holding_time():
    trades = [_trade(10.0, duration_minutes=20), _trade(-5.0, duration_minutes=40)]

    assert average_trade_duration(trades) == timedelta(minutes=30)


# --- exposure_pct ---


def test_exposure_pct_with_zero_session_minutes_is_zero():
    trades = [_trade(10.0, duration_minutes=30)]

    assert exposure_pct(trades, total_session_minutes=0) == 0.0


def test_exposure_pct_computes_fraction_of_session_time_held():
    trades = [_trade(10.0, duration_minutes=30), _trade(-5.0, duration_minutes=15)]

    # 45 minutes held out of a 375-minute (9:15-15:30) session.
    assert exposure_pct(trades, total_session_minutes=375) == pytest.approx(45 / 375)


# --- Sharpe / Sortino / Calmar ---


def test_sharpe_and_sortino_are_zero_with_fewer_than_two_trading_days():
    trades = [_trade(100.0, day=30), _trade(-40.0, day=30)]

    assert sharpe_ratio(trades) == 0.0
    assert sortino_ratio(trades) == 0.0


def test_calmar_is_zero_when_max_drawdown_is_zero():
    trades = [_trade(100.0, day=30), _trade(50.0, day=31)]

    assert calmar_ratio(trades, max_drawdown=0.0) == 0.0


def test_sharpe_sortino_calmar_aggregate_by_calendar_day_not_by_trade():
    # Two trades on day 30 (net +60), one trade on day 31 (-40).
    trades = [
        _trade(100.0, day=30),
        _trade(-40.0, day=30),
        _trade(-40.0, day=31),
    ]

    # Daily series is [60.0, -40.0], not the four individual trade PnLs --
    # a per-trade series would materially understate day 30's volatility.
    daily = [60.0, -40.0]
    import math

    mean = sum(daily) / len(daily)
    stdev = math.sqrt(sum((v - mean) ** 2 for v in daily) / (len(daily) - 1))
    expected_sharpe = (mean / stdev) * math.sqrt(252)

    assert sharpe_ratio(trades) == pytest.approx(expected_sharpe)
