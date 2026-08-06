from collections.abc import Iterator
from datetime import datetime

from config.live_feed import LiveFeedConfig
from config.orb import ORBStrategyConfig
from config.paper_trading import PaperTradingConfig
from config.risk import RiskConfig
from domain.candle import Candle
from domain.trade import TradeDirection
from indicators.context import IndicatorContext
from indicators.opening_range import OpeningRange
from indicators.relative_volume import RelativeVolume
from indicators.vwap import VWAP
from market_data.interval import Interval
from market_data.provider import MarketDataProvider
from performance.expectancy import win_rate
from portfolio.portfolio import Portfolio
from runtime.events import RuntimeEvent
from runtime.paper_trading import PaperTradingRunner
from strategies.orb import ORBStrategy

DAY = datetime(2026, 7, 30)


def _tick(hour: int, minute: int, price: float, cumulative_volume: int) -> Candle:
    timestamp = datetime(DAY.year, DAY.month, DAY.day, hour, minute)
    return Candle(
        timestamp=timestamp,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=cumulative_volume,
    )


class FakeProvider(MarketDataProvider):
    """Replays scripted ticks. No websocket, no network, no kiteconnect."""

    def __init__(self, batches: list[list[Candle]]) -> None:
        self.batches = batches
        self.subscribed: list[list[str]] = []

    def get_historical_data(self, symbol, from_date, to_date, interval):
        return []

    def get_live_quote(self, symbol):
        return []

    def stream_ticks(self, symbols: list[str]) -> Iterator[list[Candle]]:
        self.subscribed.append(symbols)
        yield from self.batches


def _breakout_session() -> list[list[Candle]]:
    """Ticks that build a 5-minute opening range, break out, then square off.

    Two ticks per bucket so each candle carries non-zero volume, since VWAP
    ignores zero-volume candles and RelativeVolume would divide by nothing.
    """

    return [
        [_tick(9, 16, 99.0, 100), _tick(9, 17, 99.0, 200)],
        [_tick(9, 21, 100.0, 300), _tick(9, 22, 100.0, 400)],
        [_tick(9, 31, 108.0, 1400), _tick(9, 32, 108.0, 1500)],
        [_tick(15, 16, 110.0, 1600)],
    ]


def _context() -> IndicatorContext:
    context = IndicatorContext()
    context.register("vwap", VWAP())
    context.register("opening_range", OpeningRange())
    context.register("relative_volume", RelativeVolume(lookback_period=2))
    return context


def _config(**overrides) -> PaperTradingConfig:
    fields = dict(
        symbol="RELIANCE",
        live_feed=LiveFeedConfig(
            interval=Interval.FIVE_MINUTE,
            poll_timeout_seconds=0.01,
            stop_at_market_close=False,
        ),
    )
    fields.update(overrides)
    return PaperTradingConfig(**fields)


def _runner(batches=None, config=None, on_event=None, portfolio=None) -> PaperTradingRunner:
    return PaperTradingRunner(
        provider=FakeProvider(batches if batches is not None else _breakout_session()),
        strategy=ORBStrategy("RELIANCE", config=ORBStrategyConfig()),
        config=config or _config(),
        indicator_context=_context(),
        portfolio=portfolio,
        on_event=on_event,
    )


# --- End to end: a complete paper trade ---


def test_paper_trading_runs_a_full_trade_from_live_candles_to_trade_record():
    runner = _runner()

    runner.run()

    assert len(runner.trade_log) == 1
    trade = runner.trade_log.records[0]
    assert trade.symbol == "RELIANCE"
    assert trade.direction is TradeDirection.BUY
    assert trade.entry_price == 108.0
    assert trade.exit_price == 110.0
    assert trade.reason == "end_of_day_exit"
    assert trade.pnl > 0
    assert runner.state.error_count == 0


def test_paper_trading_updates_portfolio_cash_and_realized_pnl():
    runner = _runner()

    runner.run()

    trade = runner.trade_log.records[0]
    expected_pnl = (trade.exit_price - trade.entry_price) * trade.quantity
    assert runner.portfolio.realized_pnl == expected_pnl
    assert runner.portfolio.cash == 100_000.0 + expected_pnl
    assert runner.portfolio.positions == {}


def test_paper_trading_sizes_position_through_the_real_risk_manager():
    runner = _runner()

    runner.run()

    # RiskConfig default allocates 10% of capital: int(100_000 * 0.1 / 108).
    assert runner.trade_log.records[0].quantity == 92


def test_paper_trading_trade_log_feeds_existing_performance_functions():
    runner = _runner()

    runner.run()

    # Metrics are not recomputed by paper trading; the caller uses performance/.
    assert win_rate(runner.trade_log.records) == 1.0


def test_paper_trading_emits_runtime_events():
    events: list[RuntimeEvent] = []
    runner = _runner(on_event=lambda event, payload: events.append(event))

    runner.run()

    assert RuntimeEvent.SIGNAL_GENERATED in events
    assert RuntimeEvent.ORDER_SUBMITTED in events
    assert RuntimeEvent.ORDER_FILLED in events
    assert RuntimeEvent.TRADE_CLOSED in events
    assert events[-1] is RuntimeEvent.RUNTIME_STOPPED


# --- Composition and wiring ---


def test_runner_shares_one_execution_provider_between_engine_and_order_manager():
    runner = _runner()

    # Two instances would leave one armed with prices and the other placing
    # orders, failing on the first trade.
    assert runner._engine.execution_provider is runner._engine.order_manager.provider


def test_runner_subscribes_the_feed_to_the_configured_symbol():
    provider = FakeProvider(_breakout_session())
    runner = PaperTradingRunner(
        provider=provider,
        strategy=ORBStrategy("RELIANCE", config=ORBStrategyConfig()),
        config=_config(),
        indicator_context=_context(),
    )

    runner.run()

    assert provider.subscribed == [["RELIANCE"]]


def test_runner_defaults_portfolio_to_configured_starting_capital():
    runner = _runner(config=_config(starting_capital=250_000.0), batches=[])

    assert runner.portfolio.cash == 250_000.0


def test_runner_accepts_an_injected_portfolio():
    portfolio = Portfolio(cash=42_000.0)
    runner = _runner(portfolio=portfolio, batches=[])

    assert runner.portfolio is portfolio


def test_runner_passes_exchange_through_to_order_requests():
    runner = _runner(config=_config(exchange="BSE"))

    assert runner._engine.order_request_builder.exchange == "BSE"


def test_runner_uses_configured_risk_settings():
    config = _config(risk=RiskConfig(max_trades_per_day=0))
    runner = _runner(config=config)

    runner.run()

    # Risk rejects the entry, so no trade is ever recorded.
    assert runner.trade_log.records == []


# --- Lifecycle ---


def test_runner_state_reports_progress():
    runner = _runner()

    runner.run()

    assert runner.state.candles_processed == 4
    assert runner.state.is_stopped is True


def test_runner_stop_halts_the_session():
    events: list[RuntimeEvent] = []
    runner = _runner()

    def stop_on_first_candle(event, payload):
        if event is RuntimeEvent.CANDLE_RECEIVED:
            runner.stop()
        events.append(event)

    runner._engine.on_event = stop_on_first_candle
    runner.run()

    assert runner.state.candles_processed == 1
    assert runner.state.is_stopped is True


def test_runner_survives_a_strategy_error_when_continue_on_error_is_true():
    class ExplodingStrategy(ORBStrategy):
        def generate_signal(self, candle, context):
            raise RuntimeError("strategy blew up")

    runner = PaperTradingRunner(
        provider=FakeProvider(_breakout_session()),
        strategy=ExplodingStrategy("RELIANCE", config=ORBStrategyConfig()),
        config=_config(),
        indicator_context=_context(),
    )

    runner.run()

    # A live session keeps running past a recoverable per-candle failure.
    assert runner.state.error_count == 4
    assert runner.state.candles_processed == 4
