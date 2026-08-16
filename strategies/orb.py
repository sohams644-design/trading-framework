"""Opening Range Breakout strategy."""

from __future__ import annotations

from enum import Enum

from config import ORBStrategyConfig
from domain.candle import Candle
from domain.signal import Signal
from indicators.context import IndicatorContext
from strategies.base_strategy import BaseStrategy


class PositionState(Enum):
    """Lightweight position state tracked by ORBStrategy."""

    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


class ORBStrategy(BaseStrategy):
    """Converts indicator state into ORB entry and exit signals."""

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

    def _build_entry_signal(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> Signal | None:
        if self.position_state is not PositionState.FLAT:
            return None
        if self.config.session.is_square_off_time(candle.timestamp):
            return None
        if not self._entry_filters_ready(context):
            return None
        if not self._relative_volume_confirmed(context):
            return None

        if self._long_entry(candle, context):
            self.position_state = PositionState.LONG
            self._set_trade_levels(candle, context)
            return Signal.buy(
                self.symbol,
                candle.timestamp,
                candle.close,
                reason="orb_long_breakout",
            )

        if self._short_entry(candle, context):
            self.position_state = PositionState.SHORT
            self._set_trade_levels(candle, context)
            return Signal.sell(
                self.symbol,
                candle.timestamp,
                candle.close,
                reason="orb_short_breakout",
            )

        return None

    def _set_trade_levels(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> None:
        self.entry_price = candle.close

        if self.position_state is PositionState.LONG:
            self.stop_loss = context.opening_range.opening_low
            risk = self.entry_price - self.stop_loss
            self.profit_target = (
                self.entry_price
                + risk * self.config.risk_reward_ratio
            )
        elif self.position_state is PositionState.SHORT:
            self.stop_loss = context.opening_range.opening_high
            risk = self.stop_loss - self.entry_price
            self.profit_target = (
                self.entry_price
                - risk * self.config.risk_reward_ratio
            )

    def _stop_loss_exit(
        self,
        candle: Candle,
    ) -> Signal | None:
        if self.stop_loss is None:
            return None

        if (
            self.position_state is PositionState.LONG
            and candle.low <= self.stop_loss
        ):
            return self._exit_current_position(
                candle,
                "stop_loss",
            )

        if (
            self.position_state is PositionState.SHORT
            and candle.high >= self.stop_loss
        ):
            return self._exit_current_position(
                candle,
                "stop_loss",
            )

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
                candle,
                "profit_target",
            )

        if (
            self.position_state is PositionState.SHORT
            and candle.low <= self.profit_target
        ):
            return self._exit_current_position(
                candle,
                "profit_target",
            )

        return None

    def _build_exit_signal(
        self,
        candle: Candle,
        context: IndicatorContext,
    ) -> Signal | None:
        if self.position_state is PositionState.FLAT:
            return None

        stop_exit = self._stop_loss_exit(candle)
        if stop_exit is not None:
            return stop_exit

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
        return (
            self.config.allow_long
            and context.opening_range.breakout_above
            and context.vwap.value is not None
            and candle.close > context.vwap.value
        )

    def _short_entry(self, candle: Candle, context: IndicatorContext) -> bool:
        return (
            self.config.allow_short
            and context.opening_range.breakout_below
            and context.vwap.value is not None
            and candle.close < context.vwap.value
        )

    def _entry_filters_ready(self, context: IndicatorContext) -> bool:
        return (
            context.opening_range.range_complete
            and context.vwap.ready
            and context.relative_volume.ready
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

    def _exit_current_position(self, candle: Candle, reason: str) -> Signal:
        if self.position_state is PositionState.LONG:
            self.position_state = PositionState.FLAT
            return Signal.exit_long(
                self.symbol, candle.timestamp, candle.close, reason=reason
            )

        self.position_state = PositionState.FLAT
        return Signal.exit_short(
            self.symbol, candle.timestamp, candle.close, reason=reason
        )

    def _reset_if_new_session(self, candle: Candle) -> None:
        previous_timestamp = self._last_candle.timestamp if self._last_candle else None
        if self.config.session.should_reset(previous_timestamp, candle.timestamp):
            self.reset()
        self._last_candle = candle

    def _record(self, signal: Signal) -> Signal:
        self.last_signal = signal
        return signal
