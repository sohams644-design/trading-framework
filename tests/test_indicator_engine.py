from datetime import datetime, time

import pytest

from domain.candle import Candle
from indicators.base import Indicator
from indicators.context import IndicatorContext
from indicators.opening_range import OpeningRange
from indicators.registry import IndicatorRegistry
from indicators.relative_volume import RelativeVolume
from indicators.session import MarketSession
from indicators.vwap import VWAP


class CountingIndicator(Indicator):
    def __init__(self) -> None:
        self.updates: list[Candle] = []
        self.reset_count = 0

    def update(self, candle: Candle) -> None:
        self.updates.append(candle)

    def reset(self) -> None:
        self.reset_count += 1
        self.updates.clear()

    @property
    def ready(self) -> bool:
        return bool(self.updates)


def _candle(
    minute: int,
    open_price: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 102.0,
    volume: int = 100,
) -> Candle:
    return Candle(
        timestamp=datetime(2026, 7, 30, 9, minute),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_vwap_updates_incrementally_and_resets():
    vwap = VWAP()
    first = _candle(15, high=110, low=100, close=105, volume=10)
    second = _candle(16, high=120, low=110, close=115, volume=30)

    vwap.update(first)
    assert vwap.ready is True
    assert vwap.value == pytest.approx(105.0)

    vwap.update(second)
    assert vwap.value == pytest.approx(((105 * 10) + (115 * 30)) / 40)

    vwap.reset()
    assert vwap.ready is False
    assert vwap.value is None


def test_vwap_ignores_zero_volume_candles():
    vwap = VWAP()

    vwap.update(_candle(15, volume=0))

    assert vwap.ready is False
    assert vwap.value is None


def test_opening_range_tracks_range_completion_and_breakouts():
    opening_range = OpeningRange()

    opening_range.update(_candle(15, high=101, low=99))
    opening_range.update(_candle(20, high=103, low=98))

    assert opening_range.ready is False
    assert opening_range.opening_high == 103
    assert opening_range.opening_low == 98

    opening_range.update(_candle(30, high=104, low=100))

    assert opening_range.ready is True
    assert opening_range.range_complete is True
    assert opening_range.breakout_above is True
    assert opening_range.breakout_below is False


def test_opening_range_tracks_breakout_below_and_resets():
    opening_range = OpeningRange()
    opening_range.update(_candle(15, high=101, low=99))
    opening_range.update(_candle(30, high=100, low=97))

    assert opening_range.breakout_below is True

    opening_range.reset()

    assert opening_range.ready is False
    assert opening_range.opening_high is None
    assert opening_range.opening_low is None
    assert opening_range.breakout_above is False
    assert opening_range.breakout_below is False


def test_relative_volume_uses_prior_rolling_average_and_resets():
    relative_volume = RelativeVolume(lookback_period=3)

    relative_volume.update(_candle(15, volume=100))
    relative_volume.update(_candle(16, volume=200))
    relative_volume.update(_candle(17, volume=300))

    assert relative_volume.ready is False

    relative_volume.update(_candle(18, volume=400))

    assert relative_volume.ready is True
    assert relative_volume.current_volume_ratio == pytest.approx(2.0)

    relative_volume.reset()

    assert relative_volume.ready is False
    assert relative_volume.current_volume_ratio is None


def test_relative_volume_rejects_invalid_lookback():
    with pytest.raises(ValueError, match="lookback_period must be positive"):
        RelativeVolume(lookback_period=0)


def test_market_session_state_helpers():
    session = MarketSession(opening_range_minutes=15, square_off_time=time(15, 15))

    assert session.is_market_open(datetime(2026, 7, 30, 9, 15)) is True
    assert session.is_market_open(datetime(2026, 7, 30, 15, 31)) is False
    assert session.is_opening_range_active(datetime(2026, 7, 30, 9, 20)) is True
    assert session.is_opening_range_active(datetime(2026, 7, 30, 9, 30)) is False
    assert session.is_opening_range_complete(datetime(2026, 7, 30, 9, 30)) is True
    assert session.is_square_off_time(datetime(2026, 7, 30, 15, 15)) is True
    assert session.should_reset(
        datetime(2026, 7, 29, 15, 30),
        datetime(2026, 7, 30, 9, 15),
    ) is True


def test_indicator_registry_prevents_duplicates_and_retrieves_by_name():
    registry = IndicatorRegistry()
    indicator = CountingIndicator()

    registry.register("custom", indicator)

    assert registry.get("CUSTOM") is indicator

    with pytest.raises(ValueError, match="Indicator already registered"):
        registry.register("custom", CountingIndicator())

    with pytest.raises(KeyError, match="Indicator not registered"):
        registry.get("missing")


def test_indicator_context_updates_and_resets_registered_indicators():
    context = IndicatorContext()
    first = CountingIndicator()
    second = CountingIndicator()
    candle = _candle(15)

    context.register("first", first)
    context.register("second", second)
    context.update(candle)

    assert first.updates == [candle]
    assert second.updates == [candle]

    context.reset()

    assert first.updates == []
    assert second.updates == []
    assert first.reset_count == 1
    assert second.reset_count == 1


def test_indicator_context_default_indicators_are_accessible():
    context = IndicatorContext.with_defaults()
    candle = _candle(15, volume=100)

    context.update(candle)

    assert isinstance(context.vwap, VWAP)
    assert isinstance(context.opening_range, OpeningRange)
    assert isinstance(context.relative_volume, RelativeVolume)
    assert context.vwap.ready is True
