"""Opening Range Breakout strategy."""

from __future__ import annotations

import logging
from enum import Enum

from config import ORBStrategyConfig
from domain.candle import Candle
from domain.signal import Signal
from indicators.context import IndicatorContext
from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class PositionState(Enum):
    """Lightweight position state tracked by ORBStrategy."""

    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


class ORBStrategy(BaseStrategy):
    """Converts indicator state into ORB entry and exit signals.

    Entries are gated by: one trade per symbol per day, only within
    ``entry_window_minutes`` of the opening range completing, a breakout
    confirmed by an ATR buffer (not a bare tick above the level), a VWAP
    trend filter, and an RVOL participation filter. Once in a trade, the
    stop is the tighter of the opening-range extreme and an ATR-based
    distance, the target is a fixed R-multiple of that risk, and the stop
    trails (in ATRs) once the trade is far enough ahead.
    """

    def __init__(
        self,
        symbol: str,
        config: ORBStrategyConfig | None = None,
    ) -> None:
        super().__init__(symbol)
        self.config = config or ORBStrategyConfig()
        self.position_state = PositionState.FLAT
        self.last_signal: Signal | None = None
        self._last_candle: Candle | None = None
        self.entry_price: float | None = None
        self.stop_loss: float | None = None
        self.profit_target: float | None = None
        self.trade_taken_today = False
        self._initial_risk: float | None = None
        self._favorable_extreme: float | None = None
        self._adverse_extreme: float | None = None
        self._trailing_active = False

    def generate_signal(self, candle: Candle, context: IndicatorContext) -> Signal:
        """Generate an ORB signal from indicator state."""

        self._reset_if_new_session(candle)

        exit_signal = self._build_exit_signal(candle, context)
        if exit_signal is not None:
            return self._record(exit_signal)

        entry_signal = self._build_entry_signal(candle, context)
        if entry_signal is not None:
            return self._record(entry_signal)

        return self._record(Signal.none(self.symbol, candle.timestamp, candle.close))

    def reset(self) -> None:
        """Reset lightweight strategy state for a new session."""

        self.position_state = PositionState.FLAT
        self.last_signal = None
        self.entry_price = None
        self.stop_loss = None
        self.profit_target = None
        self.trade_taken_today = False
        self._initial_risk = None
        self._favorable_extreme = None
        self._adverse_extreme = None
        self._trailing_active = False

    def _build_entry_signal(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> Signal | None:
        if self.position_state is not PositionState.FLAT:
            return None
        if self.trade_taken_today:
            return None
        if not self.config.session.is_within_entry_window(
            candle.timestamp, self.config.entry_window_minutes
        ):
            return None
        if self.config.session.is_square_off_time(candle.timestamp):
            return None
        if not self._entry_filters_ready(context):
            return None
        if not self._relative_volume_confirmed(context):
            return None

        if self._long_entry(candle, context):
            self.position_state = PositionState.LONG
            self.trade_taken_today = True
            self._set_trade_levels(candle, context)
            self._log_trade_entry(candle, context)
            return Signal.buy(
                self.symbol,
                candle.timestamp,
                candle.close,
                reason="orb_long_breakout",
                stop_loss=self.stop_loss,
                target=self.profit_target,
            )

        if self._short_entry(candle, context):
            self.position_state = PositionState.SHORT
            self.trade_taken_today = True
            self._set_trade_levels(candle, context)
            self._log_trade_entry(candle, context)
            return Signal.sell(
                self.symbol,
                candle.timestamp,
                candle.close,
                reason="orb_short_breakout",
                stop_loss=self.stop_loss,
                target=self.profit_target,
            )

        return None

    def _set_trade_levels(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> None:
        self.entry_price = candle.close
        atr = context.atr.value or 0.0

        if self.position_state is PositionState.LONG:
            atr_stop = self.entry_price - self.config.stop_atr_multiplier * atr
            range_stop = context.opening_range.opening_low
            self.stop_loss = max(atr_stop, range_stop)
            risk = self.entry_price - self.stop_loss
            self.profit_target = self.entry_price + risk * self.config.risk_reward_ratio
        elif self.position_state is PositionState.SHORT:
            atr_stop = self.entry_price + self.config.stop_atr_multiplier * atr
            range_stop = context.opening_range.opening_high
            self.stop_loss = min(atr_stop, range_stop)
            risk = self.stop_loss - self.entry_price
            self.profit_target = self.entry_price - risk * self.config.risk_reward_ratio
        else:
            return

        self._initial_risk = risk
        self._favorable_extreme = self.entry_price
        self._adverse_extreme = self.entry_price
        self._trailing_active = False

    def _log_trade_entry(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> None:
        logger.info(
            "%s\n"
            "Opening range:\n"
            "  High = %s\n"
            "  Low = %s\n"
            "Entry:\n"
            "  %s\n"
            "Stop:\n"
            "  %s\n"
            "Target:\n"
            "  %s\n"
            "RVOL:\n"
            "  %s\n"
            "VWAP:\n"
            "  %s\n"
            "ATR:\n"
            "  %s",
            candle.timestamp,
            context.opening_range.opening_high,
            context.opening_range.opening_low,
            self.entry_price,
            self.stop_loss,
            self.profit_target,
            context.relative_volume.current_volume_ratio,
            context.vwap.value,
            context.atr.value,
        )

    def _track_excursions_and_trail_stop(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> None:
        """Update MAE/MFE tracking and ratchet the trailing stop, if active.

        Runs once per candle while a position is open, before exit checks,
        so the stop used to check this candle's exit already reflects this
        candle's own high/low. That mirrors how a live trailing stop would
        behave intrabar, but it is a simplification worth naming plainly:
        the stop can move and be hit within the same bar.
        """

        if self.entry_price is None or self._initial_risk is None or self._initial_risk <= 0:
            return

        atr = context.atr.value

        if self.position_state is PositionState.LONG:
            self._favorable_extreme = max(self._favorable_extreme, candle.high)
            self._adverse_extreme = min(self._adverse_extreme, candle.low)
            favorable_move = self._favorable_extreme - self.entry_price
            if atr is not None and favorable_move >= (
                self.config.trailing_activation_r * self._initial_risk
            ):
                trailing_stop = self._favorable_extreme - self.config.trailing_atr_multiplier * atr
                if self.stop_loss is not None and trailing_stop > self.stop_loss:
                    self.stop_loss = trailing_stop
                    self._trailing_active = True

        elif self.position_state is PositionState.SHORT:
            self._favorable_extreme = min(self._favorable_extreme, candle.low)
            self._adverse_extreme = max(self._adverse_extreme, candle.high)
            favorable_move = self.entry_price - self._favorable_extreme
            if atr is not None and favorable_move >= (
                self.config.trailing_activation_r * self._initial_risk
            ):
                trailing_stop = self._favorable_extreme + self.config.trailing_atr_multiplier * atr
                if self.stop_loss is not None and trailing_stop < self.stop_loss:
                    self.stop_loss = trailing_stop
                    self._trailing_active = True

    def _stop_loss_exit(
        self,
        candle: Candle,
    ) -> Signal | None:
        if self.stop_loss is None:
            return None

        reason = "trailing_stop" if self._trailing_active else "stop_loss"

        if (
            self.position_state is PositionState.LONG
            and candle.low <= self.stop_loss
        ):
            return self._exit_current_position(candle, reason, price=self.stop_loss)

        if (
            self.position_state is PositionState.SHORT
            and candle.high >= self.stop_loss
        ):
            return self._exit_current_position(candle, reason, price=self.stop_loss)

        return None

    def _profit_target_exit(
        self,
        candle: Candle,
    ) -> Signal | None:
        if self.profit_target is None:
            return None

        if (
            self.position_state is PositionState.LONG
            and candle.high >= self.profit_target
        ):
            return self._exit_current_position(
                candle, "profit_target", price=self.profit_target
            )

        if (
            self.position_state is PositionState.SHORT
            and candle.low <= self.profit_target
        ):
            return self._exit_current_position(
                candle, "profit_target", price=self.profit_target
            )

        return None

    def _build_exit_signal(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> Signal | None:
        if self.position_state is PositionState.FLAT:
            return None

        self._track_excursions_and_trail_stop(candle, context)

        if self.config.use_stop_loss:
            stop_exit = self._stop_loss_exit(candle)
            if stop_exit is not None:
                return stop_exit

        if self.config.use_profit_target:
            target_exit = self._profit_target_exit(candle)
            if target_exit is not None:
                return target_exit

        if self.config.exit_at_market_close and self.config.session.is_square_off_time(
            candle.timestamp
        ):
            return self._exit_current_position(candle, "end_of_day_exit")

        if self.config.exit_on_opposite_breakout:
            return self._opposite_breakout_exit(candle, context)

        return None

    def _long_entry(self, candle: Candle, context: IndicatorContext) -> bool:
        atr = context.atr.value
        if atr is None:
            return False
        confirmation_buffer = self.config.breakout_confirmation_atr_multiplier * atr
        return (
            self.config.allow_long
            and context.opening_range.breakout_above
            and context.vwap.value is not None
            and candle.close > context.vwap.value
            and candle.close > context.opening_range.opening_high + confirmation_buffer
        )

    def _short_entry(self, candle: Candle, context: IndicatorContext) -> bool:
        atr = context.atr.value
        if atr is None:
            return False
        confirmation_buffer = self.config.breakout_confirmation_atr_multiplier * atr
        return (
            self.config.allow_short
            and context.opening_range.breakout_below
            and context.vwap.value is not None
            and candle.close < context.vwap.value
            and candle.close < context.opening_range.opening_low - confirmation_buffer
        )

    def _entry_filters_ready(self, context: IndicatorContext) -> bool:
        return (
            context.opening_range.range_complete
            and context.vwap.ready
            and context.relative_volume.ready
            and context.atr.ready
        )

    def _relative_volume_confirmed(self, context: IndicatorContext) -> bool:
        relative_volume = context.relative_volume.current_volume_ratio
        return (
            relative_volume is not None
            and relative_volume >= self.config.relative_volume_threshold
        )

    def _opposite_breakout_exit(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> Signal | None:
        if (
            self.position_state is PositionState.LONG
            and context.opening_range.breakout_below
        ):
            return self._exit_current_position(candle, "opposite_breakout_exit")

        if (
            self.position_state is PositionState.SHORT
            and context.opening_range.breakout_above
        ):
            return self._exit_current_position(candle, "opposite_breakout_exit")

        return None

    def _exit_current_position(
        self,
        candle: Candle,
        reason: str,
        price: float | None = None,
    ) -> Signal:
        fill_price = price if price is not None else candle.close
        metadata = {"mae": self._current_mae(), "mfe": self._current_mfe()}

        if self.position_state is PositionState.LONG:
            self.position_state = PositionState.FLAT
            return Signal.exit_long(
                self.symbol, candle.timestamp, fill_price, reason=reason, metadata=metadata
            )

        self.position_state = PositionState.FLAT
        return Signal.exit_short(
            self.symbol, candle.timestamp, fill_price, reason=reason, metadata=metadata
        )

    def _current_mae(self) -> float | None:
        """Maximum adverse excursion so far: worst move against the trade."""

        if self._adverse_extreme is None or self.entry_price is None:
            return None
        if self.position_state is PositionState.LONG:
            return self.entry_price - self._adverse_extreme
        if self.position_state is PositionState.SHORT:
            return self._adverse_extreme - self.entry_price
        return None

    def _current_mfe(self) -> float | None:
        """Maximum favorable excursion so far: best move in the trade's favor."""

        if self._favorable_extreme is None or self.entry_price is None:
            return None
        if self.position_state is PositionState.LONG:
            return self._favorable_extreme - self.entry_price
        if self.position_state is PositionState.SHORT:
            return self.entry_price - self._favorable_extreme
        return None

    def _reset_if_new_session(self, candle: Candle) -> None:
        previous_timestamp = self._last_candle.timestamp if self._last_candle else None
        if self.config.session.should_reset(previous_timestamp, candle.timestamp):
            self.reset()
        self._last_candle = candle

    def _record(self, signal: Signal) -> Signal:
        self.last_signal = signal
        return signal
