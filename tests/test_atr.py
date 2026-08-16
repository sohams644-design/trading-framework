from datetime import datetime

import pytest

from domain.candle import Candle
from indicators.atr import ATR


def _candle(minute: int, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp=datetime(2026, 7, 30, 9, minute),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def test_atr_rejects_non_positive_period():
    with pytest.raises(ValueError, match="period must be positive"):
        ATR(period=0)


def test_atr_not_ready_before_seed_window_completes():
    atr = ATR(period=3)

    atr.update(_candle(15, high=105, low=95, close=100))
    atr.update(_candle(16, high=106, low=96, close=101))

    assert atr.ready is False
    assert atr.value is None


def test_atr_first_candle_true_range_is_high_minus_low():
    atr = ATR(period=1)

    atr.update(_candle(15, high=105, low=95, close=100))

    # No previous close yet, so true range collapses to the candle's own range.
    assert atr.ready is True
    assert atr.value == pytest.approx(10.0)


def test_atr_seeds_with_simple_average_of_first_period_true_ranges():
    atr = ATR(period=2)

    atr.update(_candle(15, high=105, low=95, close=100))  # TR = 10 (no prior close)
    atr.update(_candle(16, high=108, low=99, close=104))  # TR = max(9, 8, 1) = 9

    assert atr.ready is True
    assert atr.value == pytest.approx((10 + 9) / 2)


def test_atr_applies_wilder_smoothing_after_seeding():
    atr = ATR(period=2)
    atr.update(_candle(15, high=105, low=95, close=100))  # TR = 10
    atr.update(_candle(16, high=108, low=99, close=104))  # TR = 9, seeds at 9.5

    atr.update(_candle(17, high=110, low=103, close=106))  # TR = max(7, 6, 1) = 7

    expected = ((2 - 1) * 9.5 + 7) / 2
    assert atr.value == pytest.approx(expected)


def test_atr_true_range_considers_gaps_beyond_the_current_bar():
    atr = ATR(period=1)
    atr.update(_candle(15, high=100, low=95, close=99))

    # A gap-down bar: high/low range is only 3, but the gap from the prior
    # close (99) down to this bar's low (85) is a bigger true range.
    atr.update(_candle(16, high=90, low=85, close=88))

    assert atr.value == pytest.approx(max(90 - 85, abs(90 - 99), abs(85 - 99)))
    assert atr.value == pytest.approx(14.0)


def test_atr_reset_clears_state():
    atr = ATR(period=2)
    atr.update(_candle(15, high=105, low=95, close=100))
    atr.update(_candle(16, high=108, low=99, close=104))
    assert atr.ready is True

    atr.reset()

    assert atr.ready is False
    assert atr.value is None
