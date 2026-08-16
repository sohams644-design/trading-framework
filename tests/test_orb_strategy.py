from datetime import datetime

from config import ORBStrategyConfig
from domain.candle import Candle
from domain.signal import SignalAction
from indicators.atr import ATR
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
    """A minimal, fast-seeding indicator context for hand-verifiable tests.

    ATR(period=1) and RelativeVolume(lookback_period=1) both become ready
    after a single prior candle, so every scenario below needs only as many
    warm-up candles as the opening range itself requires -- and with
    period=1, ATR's Wilder smoothing collapses to "the latest true range",
    which keeps every expected number in this file simple arithmetic
    instead of a multi-candle smoothing chain.
    """

    context = IndicatorContext()
    context.register("vwap", VWAP())
    context.register("opening_range", OpeningRange())
    context.register("relative_volume", RelativeVolume(lookback_period=1))
    context.register("atr", ATR(period=1))
    return context


def _warm_opening_range(context: IndicatorContext) -> None:
    """Scenario L's single range-building candle: opening_high=110, opening_low=90."""

    context.update(_candle(9, 15, high=110, low=90, close=100, volume=100))


def _long_breakout_candle(volume: int = 500) -> Candle:
    """Scenario L's entry candle.

    ATR (from this candle's own true range against the prior close of 100)
    is 25, so the confirmation buffer is 0.15*25=3.75 -- close 122 clears
    opening_high 110 + 3.75 = 113.75. VWAP works out to ~118.06, and close
    122 is above it. Stop is max(entry - 1.5*ATR, opening_low) =
    max(122 - 37.5, 90) = 90 (the range is the tighter bound here); risk is
    32, so target is 122 + 2*32 = 186.
    """

    return _candle(9, 30, high=125, low=118, close=122, volume=volume)


def _enter_long(strategy: ORBStrategy, context: IndicatorContext) -> None:
    _warm_opening_range(context)
    breakout = _long_breakout_candle()
    context.update(breakout)
    strategy.generate_signal(breakout, context)


# --- Basic entry generation ---


def test_orb_strategy_generates_long_breakout_signal():
    context = _context()
    strategy = ORBStrategy("reliance")
    _warm_opening_range(context)
    breakout = _long_breakout_candle()
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.BUY
    assert signal.symbol == "RELIANCE"
    assert signal.price == 122
    assert signal.reason == "orb_long_breakout"
    assert strategy.position_state is PositionState.LONG


def test_orb_strategy_generates_short_breakout_signal():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    context.update(_candle(9, 15, high=101, low=99, close=100, volume=100))
    breakout = _candle(9, 30, high=100, low=90, close=93, volume=500)
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.SELL
    assert signal.price == 93
    assert signal.reason == "orb_short_breakout"
    assert strategy.position_state is PositionState.SHORT


def test_orb_strategy_entry_signal_carries_stop_loss_and_target():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _warm_opening_range(context)
    breakout = _long_breakout_candle()
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.stop_loss == 90.0
    assert signal.target == 186.0


def test_orb_strategy_returns_no_signal_without_breakout():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _warm_opening_range(context)
    inside_range = _candle(9, 30, high=109, low=91, close=105, volume=300)
    context.update(inside_range)

    signal = strategy.generate_signal(inside_range, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_rejects_low_relative_volume():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _warm_opening_range(context)
    breakout = _long_breakout_candle(volume=150)  # ratio 150/100 = 1.5 < threshold 2.0
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


def test_orb_strategy_rejects_weak_breakout_that_fails_atr_confirmation():
    """High clears the range, but close doesn't clear it by a full buffer."""

    context = _context()
    strategy = ORBStrategy("RELIANCE")
    context.update(_candle(9, 15, high=101, low=99, close=100, volume=100))
    # ATR (true range against prior close 100) = max(7, 5, 2) = 7.
    # Buffer = 0.15*7 = 1.05, so close must clear 101 + 1.05 = 102.05.
    # This candle's high (105) breaks out, but its close (101.5) doesn't.
    weak_breakout = _candle(9, 30, high=105, low=98, close=101.5, volume=500)
    context.update(weak_breakout)

    signal = strategy.generate_signal(weak_breakout, context)

    assert context.opening_range.breakout_above is True
    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_honors_configuration_changes():
    context = _context()
    config = ORBStrategyConfig(allow_long=False)
    strategy = ORBStrategy("RELIANCE", config=config)
    _warm_opening_range(context)
    breakout = _long_breakout_candle()
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_returns_no_signal_before_opening_range_completes():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    early_breakout = _candle(9, 20, high=110, low=103, close=108, volume=300)
    context.update(early_breakout)

    signal = strategy.generate_signal(early_breakout, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


# --- Entry window (redesign) ---


def test_orb_strategy_rejects_entry_after_the_entry_window_closes():
    """Otherwise-identical to the passing long breakout, just timestamped
    past the 45-minute default entry window (range completes 9:30, window
    closes 10:15)."""

    context = _context()
    strategy = ORBStrategy("RELIANCE")
    context.update(_candle(9, 15, high=110, low=90, close=100, volume=100))
    late_breakout = Candle(
        timestamp=datetime(2026, 7, 30, 10, 20),
        open=122, high=125, low=118, close=122, volume=500,
    )
    context.update(late_breakout)

    signal = strategy.generate_signal(late_breakout, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


def test_orb_strategy_accepts_entry_within_a_widened_window():
    context = _context()
    config = ORBStrategyConfig(entry_window_minutes=120)
    strategy = ORBStrategy("RELIANCE", config=config)
    context.update(_candle(9, 15, high=110, low=90, close=100, volume=100))
    late_breakout = Candle(
        timestamp=datetime(2026, 7, 30, 10, 20),
        open=122, high=125, low=118, close=122, volume=500,
    )
    context.update(late_breakout)

    signal = strategy.generate_signal(late_breakout, context)

    assert signal.action is SignalAction.BUY


# --- One trade per day (same-day re-entry lock) ---


def test_orb_strategy_prevents_duplicate_long_entries():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _enter_long(strategy, context)

    second_candle = _candle(9, 35, high=124, low=120, close=123, volume=200)
    context.update(second_candle)
    second_signal = strategy.generate_signal(second_candle, context)

    assert strategy.position_state is PositionState.LONG
    assert second_signal.action is SignalAction.HOLD


def test_orb_strategy_blocks_reentry_after_a_stop_loss_exit_same_day():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _enter_long(strategy, context)
    assert strategy.position_state is PositionState.LONG

    stop_candle = _candle(9, 35, high=95, low=85, close=91, volume=100)
    context.update(stop_candle)
    exit_signal = strategy.generate_signal(stop_candle, context)
    assert exit_signal.reason == "stop_loss"
    assert strategy.position_state is PositionState.FLAT

    # Even a fresh, otherwise-valid-looking breakout candle must not reopen
    # a position -- this is the same "sticky breakout after exit" failure
    # mode as the 15:15 bug, just triggered by a stop instead of a clock.
    another_breakout = _candle(9, 40, high=140, low=130, close=135, volume=500)
    context.update(another_breakout)
    signal = strategy.generate_signal(another_breakout, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.FLAT


# --- Stop placement: tighter of ATR-based and range-based ---


def test_orb_strategy_stop_uses_atr_when_it_is_tighter_than_the_range():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    # Wide range (opening_low=50), but the breakout candle's own true range
    # is small (its close, 148, sits near the range high, 150), so ATR is
    # small and the ATR-based stop ends up much closer to entry than the
    # range-based one.
    context.update(_candle(9, 15, high=150, low=50, close=148, volume=100))
    breakout = _candle(9, 30, high=153, low=151, close=152, volume=500)
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.BUY
    # ATR = max(2, 5, 3) = 5. atr_stop = 152 - 1.5*5 = 144.5 > range_stop 50.
    assert signal.stop_loss == 144.5


def test_orb_strategy_stop_uses_range_when_it_is_tighter_than_atr():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    # Narrow range (opening_low=99), but the breakout candle gaps hard away
    # from the prior close, producing a large true range -- the ATR-based
    # stop would be far looser than just using the range's own edge.
    context.update(_candle(9, 15, high=101, low=99, close=100, volume=100))
    breakout = _candle(9, 30, high=130, low=115, close=125, volume=500)
    context.update(breakout)

    signal = strategy.generate_signal(breakout, context)

    assert signal.action is SignalAction.BUY
    # ATR = max(15, 30, 15) = 30. atr_stop = 125 - 1.5*30 = 80 < range_stop 99.
    assert signal.stop_loss == 99.0


# --- Realistic exit fill price (intrabar stop/target, not candle close) ---


def test_orb_strategy_stop_loss_exit_fills_at_the_stop_price_not_candle_close():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _enter_long(strategy, context)  # stop_loss == 90.0

    stop_candle = _candle(9, 35, high=95, low=88, close=91, volume=100)
    context.update(stop_candle)
    signal = strategy.generate_signal(stop_candle, context)

    assert signal.action is SignalAction.EXIT_LONG
    assert signal.reason == "stop_loss"
    assert signal.price == 90.0  # not 91 (the candle's close)


def test_orb_strategy_profit_target_exit_fills_at_the_target_price_not_candle_close():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _enter_long(strategy, context)  # profit_target == 186.0

    target_candle = _candle(9, 35, high=190, low=184, close=188, volume=100)
    context.update(target_candle)
    signal = strategy.generate_signal(target_candle, context)

    assert signal.action is SignalAction.EXIT_LONG
    assert signal.reason == "profit_target"
    assert signal.price == 186.0  # not 188 (the candle's close)


# --- use_stop_loss / use_profit_target flags actually gate exits ---


def test_orb_strategy_use_stop_loss_false_disables_the_stop_exit():
    context = _context()
    strategy = ORBStrategy("RELIANCE", config=ORBStrategyConfig(use_stop_loss=False))
    _enter_long(strategy, context)

    breach_candle = _candle(9, 35, high=95, low=85, close=90, volume=100)
    context.update(breach_candle)
    signal = strategy.generate_signal(breach_candle, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.LONG


def test_orb_strategy_use_profit_target_false_disables_the_target_exit():
    context = _context()
    strategy = ORBStrategy("RELIANCE", config=ORBStrategyConfig(use_profit_target=False))
    _enter_long(strategy, context)

    breach_candle = _candle(9, 35, high=190, low=180, close=185, volume=100)
    context.update(breach_candle)
    signal = strategy.generate_signal(breach_candle, context)

    assert signal.action is SignalAction.HOLD
    assert strategy.position_state is PositionState.LONG


# --- Trailing stop ---


def test_orb_strategy_trailing_stop_activates_and_never_loosens():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _enter_long(strategy, context)  # entry 122, initial stop 90, initial risk 32

    # Favorable move of 29 >= trailing_activation_r(1.0) * risk(32)? No --
    # 29 < 32, so trailing should NOT activate yet.
    almost_candle = _candle(9, 35, high=151, low=149, close=150, volume=100)
    context.update(almost_candle)
    strategy.generate_signal(almost_candle, context)
    assert strategy.stop_loss == 90.0

    # Now favorable move is 156-122=34 >= 32: trailing activates.
    # ATR (true range against prior close 150) = max(4,6,2)=6.
    # trailing_stop = 156 - 1.0*6 = 150 > current stop 90 -> ratchets to 150.
    # This candle's own low (152) stays above 150, so activating the trail
    # doesn't itself trigger an exit on the same bar.
    activate_candle = _candle(9, 40, high=156, low=152, close=153, volume=100)
    context.update(activate_candle)
    signal = strategy.generate_signal(activate_candle, context)
    assert signal.action is SignalAction.HOLD
    assert strategy.stop_loss == 150.0

    # A sharp pullback whose own trailing math would suggest a LOOSER stop
    # (favorable_extreme is still 156, this candle's high of 140 doesn't
    # beat it, but its huge true range pulls the candidate trail down to
    # 156 - 23 = 133) must not loosen the stop: 133 < 150, so it's rejected
    # and the stop stays at 150.
    pullback_candle = _candle(9, 45, high=140, low=130, close=138, volume=100)
    context.update(pullback_candle)
    signal = strategy.generate_signal(pullback_candle, context)

    # 130 <= 150 (the still-150 trailed stop) -> exits, at the stop price,
    # tagged as a trailing-stop exit rather than the original fixed stop.
    assert signal.action is SignalAction.EXIT_LONG
    assert signal.reason == "trailing_stop"
    assert signal.price == 150.0


# --- MAE / MFE tracking ---


def test_orb_strategy_tracks_mae_and_mfe_across_the_trade():
    context = _context()
    strategy = ORBStrategy("RELIANCE")
    _enter_long(strategy, context)  # entry 122

    favorable_then_pullback = _candle(9, 35, high=130, low=115, close=125, volume=100)
    context.update(favorable_then_pullback)
    strategy.generate_signal(favorable_then_pullback, context)

    eod_candle = _candle(15, 15, high=128, low=120, close=124, volume=100)
    context.update(eod_candle)
    signal = strategy.generate_signal(eod_candle, context)

    assert signal.reason == "end_of_day_exit"
    assert signal.metadata["mfe"] == 8.0  # best price 130 - entry 122
    assert signal.metadata["mae"] == 7.0  # entry 122 - worst price 115


# --- Session lifecycle exits (unchanged behavior) ---


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
    context.update(_candle(9, 15, high=110, low=90, close=100, volume=100))
    opposite_breakout = _candle(9, 30, high=95, low=80, close=85, volume=300)
    context.update(opposite_breakout)

    signal = strategy.generate_signal(opposite_breakout, context)

    assert signal.action is SignalAction.EXIT_LONG
    assert signal.reason == "opposite_breakout_exit"
    assert strategy.position_state is PositionState.FLAT
