from datetime import datetime

import pytest

from config.orb import ORBStrategyConfig
from config.risk import RiskConfig
from domain.candle import Candle
from domain.trade import TradeDirection
from execution.order_manager import OrderManager
from execution.order_request import OrderRequest, OrderType, Product
from execution.order_request_builder import OrderRequestBuilder
from execution.paper_broker import PaperExecutionProvider
from execution.simulated_execution_provider import SimulatedExecutionProvider
from indicators.context import IndicatorContext
from indicators.opening_range import OpeningRange
from indicators.relative_volume import RelativeVolume
from indicators.vwap import VWAP
from portfolio.portfolio import Portfolio
from risk.risk_manager import RiskManager
from runtime.config import RuntimeConfig
from runtime.engine import RuntimeEngine
from runtime.events import RuntimeEvent
from state.runtime_state import RuntimeState, RuntimeStatus
from strategies.base_strategy import BaseStrategy
from strategies.orb import ORBStrategy


def _candle(date, hour: int, minute: int, high: float, low: float, close: float, volume: int) -> Candle:
    return Candle(
        timestamp=datetime(date.year, date.month, date.day, hour, minute),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _build_runtime(
    strategy: BaseStrategy | None = None,
    config: RuntimeConfig | None = None,
    on_event=None,
) -> tuple[RuntimeEngine, Portfolio]:
    indicator_context = IndicatorContext()
    indicator_context.register("vwap", VWAP())
    indicator_context.register("opening_range", OpeningRange())
    indicator_context.register("relative_volume", RelativeVolume(lookback_period=2))

    execution_provider = SimulatedExecutionProvider()
    portfolio = Portfolio(cash=100_000.0)
    engine = RuntimeEngine(
        strategy=strategy or ORBStrategy("RELIANCE", config=ORBStrategyConfig()),
        indicator_context=indicator_context,
        risk_manager=RiskManager(RiskConfig()),
        order_manager=OrderManager(execution_provider),
        execution_provider=execution_provider,
        order_request_builder=OrderRequestBuilder(exchange="NSE"),
        portfolio=portfolio,
        config=config,
        on_event=on_event,
    )
    return engine, portfolio


def _winning_day(date) -> list[Candle]:
    return [
        _candle(date, 9, 15, high=101, low=90, close=99, volume=100),
        _candle(date, 9, 20, high=102, low=91, close=100, volume=100),
        _candle(date, 9, 30, high=110, low=103, close=108, volume=300),
        _candle(date, 15, 15, high=110, low=100, close=106, volume=100),
    ]


class ExplodingStrategy(BaseStrategy):
    """Raises on every candle, to verify stage error isolation."""

    def generate_signal(self, candle, context):
        raise RuntimeError("strategy blew up")


class ExplodingRiskManager(RiskManager):
    def evaluate(self, signal, context):
        raise RuntimeError("risk blew up")


# --- RuntimeState ---


def test_runtime_state_defaults_to_not_started_with_generated_id():
    state = RuntimeState()

    assert state.status is RuntimeStatus.NOT_STARTED
    assert state.is_running is False
    assert state.is_stopped is False
    assert len(state.runtime_id) == 8
    assert state.candles_processed == 0
    assert state.error_count == 0


def test_runtime_state_ids_are_unique_per_instance():
    assert RuntimeState().runtime_id != RuntimeState().runtime_id


# --- ExecutionProvider.advance default ---


def test_execution_provider_advance_defaults_to_noop():
    provider = PaperExecutionProvider()

    # Should neither raise nor change behaviour for a non-simulated provider.
    provider.advance(_candle(datetime(2026, 7, 30), 9, 15, 101, 90, 99, 100))


def test_simulated_execution_provider_overrides_advance():
    provider = SimulatedExecutionProvider()
    provider.advance(_candle(datetime(2026, 7, 30), 9, 15, 101, 90, 99, 100))

    order = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        side=TradeDirection.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        product=Product.INTRADAY,
    )
    result = provider.place_order(order)

    assert result.fill_price == 99.0


# --- Runtime loop ---


def test_runtime_engine_runs_full_pipeline_and_records_trade():
    engine, portfolio = _build_runtime()

    engine.run(_winning_day(datetime(2026, 7, 30)))

    assert len(portfolio.trade_log) == 1
    assert engine.state.candles_processed == 4
    assert engine.state.error_count == 0
    assert engine.state.status is RuntimeStatus.STOPPED
    assert engine.state.started_at is not None
    assert engine.state.stopped_at is not None


def test_runtime_engine_resets_indicators_across_sessions():
    engine, portfolio = _build_runtime()

    engine.run(_winning_day(datetime(2026, 7, 30)))
    engine.run(
        [
            _candle(datetime(2026, 7, 31), 9, 15, high=95, low=85, close=90, volume=100),
            _candle(datetime(2026, 7, 31), 9, 20, high=96, low=86, close=91, volume=100),
        ]
    )

    assert engine.indicator_context.opening_range.opening_high == 96.0
    assert engine.state.current_session_date == datetime(2026, 7, 31).date()


def test_runtime_engine_stop_halts_processing_mid_feed():
    engine, portfolio = _build_runtime()
    candles = _winning_day(datetime(2026, 7, 30))

    def stop_after_first(event, payload):
        if event is RuntimeEvent.CANDLE_RECEIVED:
            engine.stop()

    engine.on_event = stop_after_first
    engine.run(candles)

    assert engine.state.candles_processed == 1
    assert engine.state.is_stopped is True


def test_runtime_engine_pause_observes_candles_without_trading():
    engine, portfolio = _build_runtime()

    engine._start()
    engine.pause()
    for candle in _winning_day(datetime(2026, 7, 30)):
        engine.process_candle(candle)

    assert engine.state.status is RuntimeStatus.PAUSED
    assert engine.state.candles_processed == 4
    assert portfolio.trade_log.records == []
    assert portfolio.positions == {}


def test_runtime_engine_resume_restores_trading():
    engine, portfolio = _build_runtime()

    engine._start()
    engine.pause()
    engine.resume()
    for candle in _winning_day(datetime(2026, 7, 30)):
        engine.process_candle(candle)

    assert engine.state.status is RuntimeStatus.RUNNING
    assert len(portfolio.trade_log) == 1


# --- Error handling ---


def test_runtime_engine_isolates_strategy_errors_and_continues():
    engine, portfolio = _build_runtime(strategy=ExplodingStrategy("RELIANCE"))

    engine.run(_winning_day(datetime(2026, 7, 30)))

    assert engine.state.error_count == 4
    assert engine.state.candles_processed == 4
    assert portfolio.trade_log.records == []


def test_runtime_engine_stops_on_first_error_when_continue_on_error_is_false():
    engine, _ = _build_runtime(
        strategy=ExplodingStrategy("RELIANCE"),
        config=RuntimeConfig(continue_on_error=False),
    )

    engine.run(_winning_day(datetime(2026, 7, 30)))

    assert engine.state.error_count == 1
    assert engine.state.candles_processed == 1
    assert engine.state.is_stopped is True


def test_runtime_engine_isolates_risk_errors():
    indicator_context = IndicatorContext()
    indicator_context.register("vwap", VWAP())
    indicator_context.register("opening_range", OpeningRange())
    indicator_context.register("relative_volume", RelativeVolume(lookback_period=2))

    execution_provider = SimulatedExecutionProvider()
    portfolio = Portfolio(cash=100_000.0)
    engine = RuntimeEngine(
        strategy=ORBStrategy("RELIANCE", config=ORBStrategyConfig()),
        indicator_context=indicator_context,
        risk_manager=ExplodingRiskManager(RiskConfig()),
        order_manager=OrderManager(execution_provider),
        execution_provider=execution_provider,
        order_request_builder=OrderRequestBuilder(exchange="NSE"),
        portfolio=portfolio,
    )

    engine.run(_winning_day(datetime(2026, 7, 30)))

    # Only the candles that actually produced a signal reach the risk stage.
    assert engine.state.error_count > 0
    assert portfolio.trade_log.records == []


def test_runtime_engine_handles_feed_failure_without_raising():
    engine, _ = _build_runtime()

    def exploding_feed():
        yield _candle(datetime(2026, 7, 30), 9, 15, 101, 90, 99, 100)
        raise ConnectionError("feed died")

    engine.run(exploding_feed())

    assert engine.state.error_count == 1
    assert engine.state.is_stopped is True


# --- Events ---


def test_runtime_engine_emits_lifecycle_and_trade_events():
    events: list[RuntimeEvent] = []
    engine, _ = _build_runtime(on_event=lambda event, payload: events.append(event))

    engine.run(_winning_day(datetime(2026, 7, 30)))

    assert events[0] is RuntimeEvent.RUNTIME_STARTED
    assert events[-1] is RuntimeEvent.RUNTIME_STOPPED
    assert RuntimeEvent.CANDLE_RECEIVED in events
    assert RuntimeEvent.SIGNAL_GENERATED in events
    assert RuntimeEvent.ORDER_SUBMITTED in events
    assert RuntimeEvent.ORDER_FILLED in events
    assert RuntimeEvent.TRADE_CLOSED in events


def test_runtime_engine_emits_error_event_with_stage():
    payloads: list[tuple] = []
    engine, _ = _build_runtime(
        strategy=ExplodingStrategy("RELIANCE"),
        on_event=lambda event, payload: payloads.append((event, payload)),
    )

    engine.run([_candle(datetime(2026, 7, 30), 9, 15, 101, 90, 99, 100)])

    errors = [payload for event, payload in payloads if event is RuntimeEvent.ERROR_OCCURRED]
    assert errors[0]["stage"] == "strategy"
    assert isinstance(errors[0]["error"], RuntimeError)


def test_runtime_engine_survives_a_failing_event_callback():
    def broken_callback(event, payload):
        raise ValueError("listener exploded")

    engine, portfolio = _build_runtime(on_event=broken_callback)

    engine.run(_winning_day(datetime(2026, 7, 30)))

    # A broken listener must never break the run itself.
    assert len(portfolio.trade_log) == 1
    assert engine.state.error_count == 0


def test_runtime_engine_emits_trade_rejected_when_risk_declines():
    events: list[tuple] = []
    engine, portfolio = _build_runtime(
        config=RuntimeConfig(),
        on_event=lambda event, payload: events.append((event, payload)),
    )
    # Exhaust the daily trade budget so the entry is rejected by TradeLimits.
    engine.risk_manager = RiskManager(RiskConfig(max_trades_per_day=0))

    engine.run(_winning_day(datetime(2026, 7, 30)))

    rejected = [payload for event, payload in events if event is RuntimeEvent.TRADE_REJECTED]
    assert rejected
    assert portfolio.trade_log.records == []
