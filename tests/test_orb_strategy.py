from datetime import datetime

from config import ORBStrategyConfig
from domain.candle import Candle
from domain.signal import SignalAction
from indicators.context import IndicatorContext
from indicators.opening_range import OpeningRange
from indicators.relative_volume import RelativeVolume
from indicators.vwap import VWAP
from strategies.orb import ORBStrategy, PositionState


def _candle(
    hour: int,
    minute: int,
    high: float,
    low: float,
    close: float,
    volume: int,
) -> Candle:
    return Candle(
        timestamp=datetime(2026, 7, 30, hour, minute),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _next_day_candle() -> Candle:
    return Candle(
        timestamp=datetime(2026, 7, 31, 9, 15),
        open=100,
        high=101,
        low=99,
        close=100,
        volume=100,
    )


def _context() -> IndicatorContext:
    context = IndicatorContext()
    context.register("vwap", VWAP())
    context.register("opening_range", OpeningRange())
    context.register("relative_volume", RelativeVolume(lookback_period=2))
    return context


def _warm_opening_range(context: IndicatorContext) -> None:
    context.update(_candle(9, 15, high=101, low=90, close=99, volume=100))
    context.update(_candle(9, 20, high=102, low=91, close=100, volume=100))


def test_orb_strategy_generates_long_breakout_signal():
    context = _context()
    strategy = ORBStrategy("reliance")
    _warm_opening_range(context)
    breakout = _candle(9, 30, high=110, low=103, close=108, volume=300)
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.BUY
    assert signal.symbol == "RELIANCE"
    assert signal.price == 108
    assert signal.reason == "orb_long_breakout"
    assert strategy.position_state is PositionState.LONG


def test_orb_strategy_generates_short_breakout_signal():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _warm_opening_range(context)
    breakout = _candle(9, 30, high=88, low=80, close=85, volume=300)
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.SELL
    assert signal.price == 85
    assert signal.reason == "orb_short_breakout"
    assert strategy.position_state is PositionState.SHORT


def test_orb_strategy_returns_no_signal_without_breakout():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _warm_opening_range(context)
    inside_range = _candle(9, 30, high=101, low=92, close=99, volume=300)
    context.update(inside_range)

    signal = strategy.generate_signal(inside_range, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_rejects_low_relative_volume():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _warm_opening_range(context)
    breakout = _candle(9, 30, high=110, low=103, close=108, volume=150)
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_rejects_long_when_price_is_below_vwap():
    context = _context()
    strategy = ORBStrategy("RELIANCE", config=ORBStrategyConfig(allow_short=False))
    context.update(_candle(9, 15, high=120, low=110, close=115, volume=1000))
    context.update(_candle(9, 20, high=119, low=111, close=114, volume=1000))
    breakout = _candle(9, 30, high=121, low=100, close=108, volume=3000)
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert context.opening_range.breakout_above is True
    assert context.vwap.value is not None
    assert breakout.close < context.vwap.value
    assert signal.action is SignalAction.HOLD


def test_orb_strategy_prevents_duplicate_long_entries():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _warm_opening_range(context)
    first_breakout = _candle(9, 30, high=110, low=103, close=108, volume=300)
    context.update(first_breakout)
    first_signal = strategy.generate_signal(first_breakout, context)

    second_breakout = _candle(9, 35, high=112, low=104, close=110, volume=300)
    context.update(second_breakout)
    second_signal = strategy.generate_signal(second_breakout, context)

    assert first_signal.action is SignalAction.BUY
    assert second_signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.LONG


def test_orb_strategy_resets_position_state_on_new_session():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    strategy.position_state = PositionState.LONG
    strategy.generate_signal(
        _candle(15, 30, high=110, low=100, close=105, volume=100), context
    )

    next_day = _next_day_candle()
    signal = strategy.generate_signal(next_day, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_honors_configuration_changes():
    context = _context()
    config = ORBStrategyConfig(allow_long=False, relative_volume_threshold=1.0)
    strategy = ORBStrategy("RELIANCE", config=config)
    _warm_opening_range(context)
    breakout = _candle(9, 30, high=110, low=103, close=108, volume=300)
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_generates_end_of_day_exit():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    strategy.position_state = PositionState.LONG
    eod_candle = _candle(15, 15, high=110, low=100, close=106, volume=100)

    signal = strategy.generate_signal(eod_candle, context)

    assert signal.action is SignalAction.EXIT_LONG
    assert signal.reason == "end_of_day_exit"
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_generates_opposite_breakout_exit_when_enabled():
    context = _context()
    config = ORBStrategyConfig(exit_on_opposite_breakout=True)
    strategy = ORBStrategy("RELIANCE", config=config)
    strategy.position_state = PositionState.LONG
    _warm_opening_range(context)
    opposite_breakout = _candle(9, 30, high=100, low=85, close=88, volume=300)
    context.update(opposite_breakout)

    signal = strategy.generate_signal(opposite_breakout, context)

    assert signal.action is SignalAction.EXIT_LONG
    assert signal.reason == "opposite_breakout_exit"
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_returns_no_signal_before_opening_range_completes():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    early_breakout = _candle(9, 20, high=110, low=103, close=108, volume=300)
    context.update(early_breakout)

    signal = strategy.generate_signal(early_breakout, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT
