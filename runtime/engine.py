"""Coordinates existing framework components over a stream of candles."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from domain.candle import Candle
from domain.risk_decision import RiskDecision
from domain.signal import Signal
from execution.order_manager import OrderManager
from execution.order_request_builder import OrderRequestBuilder
from execution.provider import ExecutionProvider
from indicators.context import IndicatorContext
from portfolio.portfolio import Portfolio
from risk.risk_manager import RiskManager
from runtime.config import RuntimeConfig
from runtime.events import RuntimeEvent, RuntimeEventCallback
from state.runtime_state import RuntimeState, RuntimeStatus
from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class RuntimeEngine:
    """Feeds candles through Indicators, Strategy, Risk, Execution, Portfolio.

    The engine is deliberately boring: it owns the loop and nothing else. It
    never calculates indicators, generates signals, evaluates risk, places
    broker orders directly, calculates PnL, or knows any strategy's rules.
    Every component it coordinates already exists and is injected.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        indicator_context: IndicatorContext,
        risk_manager: RiskManager,
        order_manager: OrderManager,
        execution_provider: ExecutionProvider,
        order_request_builder: OrderRequestBuilder,
        portfolio: Portfolio,
        config: RuntimeConfig | None = None,
        on_event: RuntimeEventCallback | None = None,
    ) -> None:
        self.strategy = strategy
        self.indicator_context = indicator_context
        self.risk_manager = risk_manager
        self.order_manager = order_manager
        self.execution_provider = execution_provider
        self.order_request_builder = order_request_builder
        self.portfolio = portfolio
        self.config = config or RuntimeConfig()
        self.on_event = on_event
        self.state = RuntimeState()
        self._previous_timestamp: datetime | None = None

    def run(self, feed: Iterable[Candle]) -> None:
        """Process candles from a feed until it ends or the engine stops.

        ``feed`` is any iterable of candles: a finite ``Replay`` for
        historical data, or a blocking live feed. Pacing is the feed's
        concern, not the engine's.
        """

        self._start()
        try:
            for candle in feed:
                if self.state.is_stopped:
                    break
                self.process_candle(candle)
        except Exception as error:
            self._handle_feed_failure(error)
        finally:
            self._finish()

    def process_candle(self, candle: Candle) -> None:
        """Run one candle through the full pipeline."""

        self.state.last_processed_candle = candle
        self.state.candles_processed += 1
        self._emit(RuntimeEvent.CANDLE_RECEIVED, {"candle": candle})
        logger.debug(
            "[%s] Candle received: %s", self.state.runtime_id, candle.timestamp
        )

        self._roll_session_if_needed(candle)
        self._previous_timestamp = candle.timestamp

        self.indicator_context.update(candle)
        self.execution_provider.advance(candle)

        if self.state.status is RuntimeStatus.PAUSED:
            return

        signal = self._run_stage("strategy", self._generate_signal, candle)
        if signal is None or not (signal.is_entry or signal.is_exit):
            return

        decision = self._run_stage("risk", self._evaluate_risk, signal)
        if decision is None:
            return
        if not decision.approved:
            self._emit(
                RuntimeEvent.TRADE_REJECTED, {"signal": signal, "decision": decision}
            )
            logger.info(
                "[%s] Trade rejected for %s: %s (%s)",
                self.state.runtime_id,
                signal.symbol,
                decision.reason,
                decision.message,
            )
            return

        quantity = self._resolve_quantity(signal, decision)
        if quantity <= 0:
            return

        self._run_stage("execution", self._submit_and_record, signal, decision, quantity)

    def pause(self) -> None:
        """Stop acting on candles while continuing to observe them."""

        if self.state.status is not RuntimeStatus.RUNNING:
            return
        self.state.status = RuntimeStatus.PAUSED
        self._emit(RuntimeEvent.RUNTIME_PAUSED, {})
        logger.info("[%s] Runtime paused.", self.state.runtime_id)

    def resume(self) -> None:
        """Resume acting on candles after a pause."""

        if self.state.status is not RuntimeStatus.PAUSED:
            return
        self.state.status = RuntimeStatus.RUNNING
        self._emit(RuntimeEvent.RUNTIME_RESUMED, {})
        logger.info("[%s] Runtime resumed.", self.state.runtime_id)

    def stop(self) -> None:
        """Request a graceful shutdown after the current candle."""

        if self.state.is_stopped:
            return
        self.state.status = RuntimeStatus.STOPPED
        self.state.stopped_at = datetime.now()
        self._emit(RuntimeEvent.RUNTIME_STOPPED, {})
        logger.info(
            "[%s] Runtime stopped after %d candles with %d errors.",
            self.state.runtime_id,
            self.state.candles_processed,
            self.state.error_count,
        )

    def _start(self) -> None:
        self.state.status = RuntimeStatus.RUNNING
        self.state.started_at = datetime.now()
        self._emit(RuntimeEvent.RUNTIME_STARTED, {})
        logger.info(
            "[%s] Runtime started (continue_on_error=%s).",
            self.state.runtime_id,
            self.config.continue_on_error,
        )

    def _finish(self) -> None:
        if not self.state.is_stopped:
            self.stop()

    def _roll_session_if_needed(self, candle: Candle) -> None:
        if not self.config.session.should_reset(self._previous_timestamp, candle.timestamp):
            return
        self.indicator_context.reset()
        self.portfolio.reset_daily_counters()
        self.state.current_session_date = candle.timestamp.date()
        self._emit(RuntimeEvent.SESSION_ROLLED, {"candle": candle})
        logger.info(
            "[%s] Session rolled to %s.", self.state.runtime_id, candle.timestamp.date()
        )

    def _generate_signal(self, candle: Candle) -> Signal:
        signal = self.strategy.generate_signal(candle, self.indicator_context)
        if signal.is_entry or signal.is_exit:
            self._emit(RuntimeEvent.SIGNAL_GENERATED, {"signal": signal})
            logger.info(
                "[%s] Signal: %s %s @ %s",
                self.state.runtime_id,
                signal.action.value,
                signal.symbol,
                signal.price,
            )
        return signal

    def _evaluate_risk(self, signal: Signal) -> RiskDecision:
        return self.risk_manager.evaluate(signal, self.portfolio.snapshot())

    def _submit_and_record(
        self, signal: Signal, decision: RiskDecision, quantity: int
    ) -> None:
        order = self.order_request_builder.build(signal, decision, quantity=quantity)
        self._emit(RuntimeEvent.ORDER_SUBMITTED, {"order": order, "signal": signal})

        result = self.order_manager.submit_order(order)
        self._emit(RuntimeEvent.ORDER_FILLED, {"order": order, "result": result})
        logger.info(
            "[%s] Order %s %s x%d -> %s",
            self.state.runtime_id,
            order.side.value,
            order.symbol,
            order.quantity,
            result.status.value,
        )

        trade = self.portfolio.on_fill(order, result, signal)
        if trade is not None:
            self._emit(RuntimeEvent.TRADE_CLOSED, {"trade": trade})
            logger.info(
                "[%s] Trade closed: %s pnl=%.2f (%s)",
                self.state.runtime_id,
                trade.symbol,
                trade.pnl,
                trade.reason,
            )

    def _resolve_quantity(self, signal: Signal, decision: RiskDecision) -> int:
        if signal.is_exit:
            position = self.portfolio.positions.get(signal.symbol)
            return abs(position.quantity) if position is not None else 0
        return decision.quantity

    def _run_stage(self, stage: str, operation, *args) -> Any:
        """Run one pipeline stage, isolating its failures from other stages."""

        try:
            return operation(*args)
        except Exception as error:
            self._handle_stage_error(stage, error)
            return None

    def _handle_stage_error(self, stage: str, error: Exception) -> None:
        self.state.error_count += 1
        self._emit(RuntimeEvent.ERROR_OCCURRED, {"stage": stage, "error": error})
        logger.exception(
            "[%s] %s stage failed on candle %s.",
            self.state.runtime_id,
            stage,
            self.state.last_processed_candle.timestamp
            if self.state.last_processed_candle
            else None,
        )
        if not self.config.continue_on_error:
            self.stop()

    def _handle_feed_failure(self, error: Exception) -> None:
        self.state.error_count += 1
        self._emit(RuntimeEvent.ERROR_OCCURRED, {"stage": "feed", "error": error})
        logger.exception("[%s] Market feed failed; stopping.", self.state.runtime_id)

    def _emit(self, event: RuntimeEvent, payload: dict[str, Any]) -> None:
        """Notify the optional event callback, never letting it break the run."""

        if self.on_event is None:
            return
        try:
            self.on_event(event, payload)
        except Exception:
            logger.exception(
                "[%s] Runtime event callback failed for %s.",
                self.state.runtime_id,
                event.value,
            )
