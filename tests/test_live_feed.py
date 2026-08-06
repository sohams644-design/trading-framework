import time
from collections.abc import Iterator
from datetime import datetime

import pytest

from config.live_feed import LiveFeedConfig
from domain.candle import Candle
from market_data.interval import Interval
from market_data.live_feed import LiveMarketFeed
from market_data.provider import MarketDataProvider
from market_data.tick_aggregator import TickAggregator

DAY = datetime(2026, 7, 30)


def _tick(hour: int, minute: int, second: int, price: float, cumulative_volume: int) -> Candle:
    timestamp = datetime(DAY.year, DAY.month, DAY.day, hour, minute, second)
    return Candle(
        timestamp=timestamp,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=cumulative_volume,
    )


def _fast_config(**overrides) -> LiveFeedConfig:
    fields = dict(poll_timeout_seconds=0.01, stop_at_market_close=False)
    fields.update(overrides)
    return LiveFeedConfig(**fields)


class FakeProvider(MarketDataProvider):
    """Yields scripted tick batches, then ends. No network, no websocket."""

    def __init__(self, batches: list[list[Candle]], fail_times: int = 0) -> None:
        self.batches = batches
        self.fail_times = fail_times
        self.stream_calls = 0

    def get_historical_data(self, symbol, from_date, to_date, interval):
        return []

    def get_live_quote(self, symbol):
        return []

    def stream_ticks(self, symbols: list[str]) -> Iterator[list[Candle]]:
        self.stream_calls += 1
        if self.stream_calls <= self.fail_times:
            raise ConnectionError("websocket dropped")
        yield from self.batches


# --- TickAggregator: bucket construction ---


def test_aggregator_builds_ohlc_from_ticks_in_one_bucket():
    aggregator = TickAggregator(Interval.ONE_MINUTE)

    assert aggregator.add(_tick(9, 30, 5, 100.0, 1000)) is None
    assert aggregator.add(_tick(9, 30, 20, 105.0, 1200)) is None
    assert aggregator.add(_tick(9, 30, 50, 98.0, 1500)) is None
    candle = aggregator.add(_tick(9, 31, 1, 102.0, 1600))

    assert candle is not None
    assert candle.timestamp == datetime(2026, 7, 30, 9, 30)
    assert candle.open == 100.0
    assert candle.high == 105.0
    assert candle.low == 98.0
    assert candle.close == 98.0


def test_aggregator_timestamps_candles_at_bucket_start_not_tick_time():
    aggregator = TickAggregator(Interval.FIVE_MINUTE)
    aggregator.add(_tick(9, 32, 14, 100.0, 500))
    candle = aggregator.add(_tick(9, 36, 0, 101.0, 900))

    assert candle.timestamp == datetime(2026, 7, 30, 9, 30)


def test_aggregator_aligns_buckets_to_session_open_not_clock_hour():
    aggregator = TickAggregator(Interval.FIFTEEN_MINUTE)
    aggregator.add(_tick(9, 20, 0, 100.0, 100))
    candle = aggregator.add(_tick(9, 31, 0, 101.0, 200))

    # Session opens 09:15, so 15-minute buckets are 09:15/09:30/09:45.
    assert candle.timestamp == datetime(2026, 7, 30, 9, 15)


# --- TickAggregator: the volume-delta correctness requirement ---


def test_aggregator_converts_cumulative_volume_into_per_bucket_volume():
    aggregator = TickAggregator(Interval.ONE_MINUTE)
    aggregator.add(_tick(9, 30, 5, 100.0, 1000))
    aggregator.add(_tick(9, 30, 50, 101.0, 1500))
    first = aggregator.add(_tick(9, 31, 5, 102.0, 1800))

    # First bucket after connecting measures from its own first tick.
    assert first.volume == 500

    second = aggregator.add(_tick(9, 32, 5, 103.0, 2100))

    # Later buckets measure from the previous bucket's final cumulative
    # figure, so no traded volume is lost between bars.
    assert second.volume == 300


def test_aggregator_never_emits_negative_volume_when_broker_resets_counter():
    aggregator = TickAggregator(Interval.ONE_MINUTE)
    aggregator.add(_tick(9, 30, 5, 100.0, 5000))
    aggregator.add(_tick(9, 31, 5, 101.0, 5200))
    # Cumulative volume moves backwards, as it would on a new trading day.
    candle = aggregator.add(_tick(9, 32, 5, 102.0, 10))

    assert candle.volume >= 0


# --- TickAggregator: lifecycle ---


def test_aggregator_has_open_bucket_reflects_state():
    aggregator = TickAggregator(Interval.ONE_MINUTE)
    assert aggregator.has_open_bucket is False

    aggregator.add(_tick(9, 30, 5, 100.0, 100))
    assert aggregator.has_open_bucket is True

    aggregator.flush()
    assert aggregator.has_open_bucket is False


def test_aggregator_flush_without_open_bucket_is_a_noop():
    assert TickAggregator(Interval.ONE_MINUTE).flush() is None


def test_aggregator_has_elapsed_detects_a_finished_bucket():
    aggregator = TickAggregator(Interval.ONE_MINUTE)
    aggregator.add(_tick(9, 30, 5, 100.0, 100))

    assert aggregator.has_elapsed(datetime(2026, 7, 30, 9, 30, 40)) is False
    assert aggregator.has_elapsed(datetime(2026, 7, 30, 9, 31, 0)) is True


def test_aggregator_drops_late_ticks_for_already_emitted_buckets():
    aggregator = TickAggregator(Interval.ONE_MINUTE)
    aggregator.add(_tick(9, 30, 5, 100.0, 100))
    aggregator.add(_tick(9, 31, 5, 101.0, 200))

    assert aggregator.add(_tick(9, 30, 40, 999.0, 150)) is None


def test_aggregator_rejects_interval_it_cannot_bucket():
    with pytest.raises(ValueError, match="not supported for tick aggregation"):
        TickAggregator(Interval.DAY)


# --- LiveMarketFeed ---


def test_live_feed_yields_completed_candles_from_ticks():
    provider = FakeProvider(
        [
            [_tick(9, 30, 5, 100.0, 1000), _tick(9, 30, 50, 105.0, 1400)],
            [_tick(9, 31, 5, 102.0, 1700)],
        ]
    )
    feed = LiveMarketFeed(provider, "reliance", config=_fast_config())

    candles = list(feed)

    assert [candle.timestamp for candle in candles] == [
        datetime(2026, 7, 30, 9, 30),
        datetime(2026, 7, 30, 9, 31),
    ]
    assert candles[0].high == 105.0
    assert candles[0].volume == 400


def test_live_feed_flushes_the_final_open_candle_when_the_stream_ends():
    provider = FakeProvider([[_tick(9, 30, 5, 100.0, 1000)]])
    feed = LiveMarketFeed(provider, "RELIANCE", config=_fast_config())

    candles = list(feed)

    # Without a final flush this candle would never be emitted at all.
    assert len(candles) == 1
    assert candles[0].timestamp == datetime(2026, 7, 30, 9, 30)


def test_live_feed_normalizes_symbol():
    feed = LiveMarketFeed(FakeProvider([]), "reliance", config=_fast_config())

    assert feed.symbol == "RELIANCE"


def test_live_feed_drops_ticks_outside_market_hours():
    provider = FakeProvider(
        [[_tick(8, 0, 0, 100.0, 100), _tick(16, 30, 0, 200.0, 300)]]
    )
    feed = LiveMarketFeed(provider, "RELIANCE", config=_fast_config())

    assert list(feed) == []


def test_live_feed_is_single_pass():
    feed = LiveMarketFeed(FakeProvider([]), "RELIANCE", config=_fast_config())
    list(feed)

    with pytest.raises(RuntimeError, match="only be iterated once"):
        list(feed)


def test_live_feed_satisfies_the_runtime_iterable_contract():
    provider = FakeProvider([[_tick(9, 30, 5, 100.0, 1000)]])
    feed = LiveMarketFeed(provider, "RELIANCE", config=_fast_config())

    # RuntimeEngine only ever does `for candle in feed`.
    for candle in feed:
        assert isinstance(candle, Candle)


# --- Reconnect and failure ---


def test_live_feed_reconnects_and_keeps_streaming():
    provider = FakeProvider(
        [[_tick(9, 30, 5, 100.0, 1000)]],
        fail_times=2,
    )
    feed = LiveMarketFeed(
        provider,
        "RELIANCE",
        config=_fast_config(max_reconnect_attempts=5, reconnect_backoff_seconds=0.001),
    )

    candles = list(feed)

    assert provider.stream_calls == 3
    assert len(candles) == 1


def test_live_feed_raises_after_exhausting_reconnect_attempts():
    provider = FakeProvider([], fail_times=99)
    feed = LiveMarketFeed(
        provider,
        "RELIANCE",
        config=_fast_config(max_reconnect_attempts=2, reconnect_backoff_seconds=0.001),
    )

    with pytest.raises(ConnectionError, match="websocket dropped"):
        list(feed)


def test_live_feed_flushes_open_candle_before_raising_on_feed_failure():
    class FailAfterOneBatch(FakeProvider):
        def stream_ticks(self, symbols):
            self.stream_calls += 1
            if self.stream_calls == 1:
                yield [_tick(9, 30, 5, 100.0, 1000)]
            raise ConnectionError("websocket dropped")

    feed = LiveMarketFeed(
        FailAfterOneBatch([]),
        "RELIANCE",
        config=_fast_config(max_reconnect_attempts=0, reconnect_backoff_seconds=0.001),
    )

    emitted = []
    with pytest.raises(ConnectionError):
        for candle in feed:
            emitted.append(candle)

    # Partial data is preserved rather than discarded on terminal failure.
    assert len(emitted) == 1
    assert emitted[0].timestamp == datetime(2026, 7, 30, 9, 30)


def test_live_feed_stop_ends_iteration():
    provider = FakeProvider([[_tick(9, 30, 5, 100.0, 1000)]])
    feed = LiveMarketFeed(provider, "RELIANCE", config=_fast_config())

    collected = []
    for candle in feed:
        collected.append(candle)
        feed.stop()

    assert len(collected) == 1


# --- Market close ---


def test_live_feed_ends_when_market_closes():
    provider = FakeProvider([[_tick(9, 30, 5, 100.0, 1000)]])
    feed = LiveMarketFeed(
        provider,
        "RELIANCE",
        config=LiveFeedConfig(poll_timeout_seconds=0.01, stop_at_market_close=True),
        now=lambda: datetime(2026, 7, 30, 16, 0),
    )

    candles = list(feed)

    # The open bucket is still flushed on the way out.
    assert len(candles) == 1


def test_live_feed_waits_before_the_open_instead_of_terminating():
    """A session started before the bell must idle, not exit immediately.

    The wait matters: the bug only shows when the queue is genuinely empty
    long enough for an idle poll to run the market-close check, which is
    exactly what happens between process start and the opening bell.
    """

    class SlowStartProvider(FakeProvider):
        def stream_ticks(self, symbols):
            self.stream_calls += 1
            time.sleep(0.05)
            yield [_tick(9, 30, 5, 100.0, 1000)]

    feed = LiveMarketFeed(
        SlowStartProvider([]),
        "RELIANCE",
        config=LiveFeedConfig(poll_timeout_seconds=0.01, stop_at_market_close=True),
        now=lambda: datetime(2026, 7, 30, 9, 0),
    )

    candles = list(feed)

    # Before the fix this returned [] because "not yet open" was read as
    # "market closed", killing the feed on its first idle poll.
    assert len(candles) == 1
    assert candles[0].timestamp == datetime(2026, 7, 30, 9, 30)


def test_live_feed_flushes_an_elapsed_candle_while_idle():
    class IdleProvider(FakeProvider):
        def stream_ticks(self, symbols):
            self.stream_calls += 1
            yield [_tick(9, 30, 5, 100.0, 1000)]
            # Then block until the consumer stops, simulating a quiet symbol.
            import time

            for _ in range(200):
                time.sleep(0.01)
            return

    feed = LiveMarketFeed(
        IdleProvider([]),
        "RELIANCE",
        config=_fast_config(),
        now=lambda: datetime(2026, 7, 30, 9, 35),
    )

    emitted = []
    for candle in feed:
        emitted.append(candle)
        feed.stop()

    # The 09:30 candle is emitted on the idle timeout, not on a later tick.
    assert len(emitted) == 1
    assert emitted[0].timestamp == datetime(2026, 7, 30, 9, 30)


# --- Zerodha adapter tick mapping (no network, no real websocket) ---


class FakeTicker:
    """Stands in for KiteTicker, driving the callbacks it would drive."""

    MODE_FULL = "full"

    def __init__(self, tick_batches: list[list[dict]]) -> None:
        self.tick_batches = tick_batches
        self.subscribed: list[int] = []
        self.closed = False
        self.on_ticks = None
        self.on_connect = None
        self.on_close = None
        self.on_error = None

    def connect(self, threaded: bool = False) -> None:
        self.on_connect(self, {})
        for batch in self.tick_batches:
            self.on_ticks(self, batch)
        self.on_close(self, 1000, "done")

    def subscribe(self, tokens: list[int]) -> None:
        self.subscribed.extend(tokens)

    def set_mode(self, mode: str, tokens: list[int]) -> None:
        self.mode = mode

    def close(self) -> None:
        self.closed = True


class FakeInstrumentManager:
    def get_token(self, symbol: str) -> int:
        return 738561


def _zerodha_provider(tick_batches: list[list[dict]]):
    from broker.zerodha_market_data import ZerodhaMarketDataProvider

    ticker = FakeTicker(tick_batches)
    provider = ZerodhaMarketDataProvider(
        instrument_manager=FakeInstrumentManager(),
        kite_client=object(),
        ticker_client=ticker,
    )
    return provider, ticker


def test_zerodha_stream_ticks_maps_ticks_to_degenerate_candles():
    provider, ticker = _zerodha_provider(
        [
            [
                {
                    "last_price": 101.5,
                    "exchange_timestamp": datetime(2026, 7, 30, 9, 30, 5),
                    "volume_traded": 4200,
                }
            ]
        ]
    )

    batches = list(provider.stream_ticks(["RELIANCE"]))

    assert len(batches) == 1
    candle = batches[0][0]
    assert candle.open == candle.high == candle.low == candle.close == 101.5
    # Cumulative volume passes through untouched; TickAggregator owns the delta.
    assert candle.volume == 4200
    assert ticker.subscribed == [738561]
    assert ticker.closed is True


def test_zerodha_stream_ticks_drops_malformed_ticks_without_stopping():
    provider, _ = _zerodha_provider(
        [
            [
                {"last_price": "not-a-number", "exchange_timestamp": datetime(2026, 7, 30, 9, 30)},
                {"exchange_timestamp": datetime(2026, 7, 30, 9, 30)},
                {"last_price": 100.0, "exchange_timestamp": None},
                {
                    "last_price": 102.0,
                    "exchange_timestamp": datetime(2026, 7, 30, 9, 30, 10),
                    "volume_traded": 10,
                },
            ]
        ]
    )

    batches = list(provider.stream_ticks(["RELIANCE"]))

    # Three bad ticks dropped, the good one survives.
    assert len(batches) == 1
    assert len(batches[0]) == 1
    assert batches[0][0].close == 102.0


def test_zerodha_stream_ticks_falls_back_to_last_trade_time():
    provider, _ = _zerodha_provider(
        [
            [
                {
                    "last_price": 99.0,
                    "last_trade_time": datetime(2026, 7, 30, 9, 31, 0),
                    "volume_traded": 5,
                }
            ]
        ]
    )

    batches = list(provider.stream_ticks(["RELIANCE"]))

    assert batches[0][0].timestamp == datetime(2026, 7, 30, 9, 31)


def test_zerodha_stream_ticks_ends_when_connection_closes():
    provider, _ = _zerodha_provider([])

    assert list(provider.stream_ticks(["RELIANCE"])) == []


# --- Integration: the runtime cannot tell a live feed from a replay ---


def test_runtime_engine_consumes_a_live_feed_exactly_like_a_replay():
    from config.orb import ORBStrategyConfig
    from config.risk import RiskConfig
    from execution.order_manager import OrderManager
    from execution.order_request_builder import OrderRequestBuilder
    from execution.simulated_execution_provider import SimulatedExecutionProvider
    from indicators.context import IndicatorContext
    from indicators.opening_range import OpeningRange
    from indicators.relative_volume import RelativeVolume
    from indicators.vwap import VWAP
    from portfolio.portfolio import Portfolio
    from risk.risk_manager import RiskManager
    from runtime.engine import RuntimeEngine
    from strategies.orb import ORBStrategy

    indicator_context = IndicatorContext()
    indicator_context.register("vwap", VWAP())
    indicator_context.register("opening_range", OpeningRange())
    indicator_context.register("relative_volume", RelativeVolume(lookback_period=2))

    execution_provider = SimulatedExecutionProvider()
    portfolio = Portfolio(cash=100_000.0)
    engine = RuntimeEngine(
        strategy=ORBStrategy("RELIANCE", config=ORBStrategyConfig()),
        indicator_context=indicator_context,
        risk_manager=RiskManager(RiskConfig()),
        order_manager=OrderManager(execution_provider),
        execution_provider=execution_provider,
        order_request_builder=OrderRequestBuilder(exchange="NSE"),
        portfolio=portfolio,
    )

    provider = FakeProvider(
        [
            [_tick(9, 16, 0, 99.0, 100), _tick(9, 16, 30, 101.0, 200)],
            [_tick(9, 21, 0, 100.0, 300)],
            [_tick(9, 31, 0, 108.0, 900)],
        ]
    )
    feed = LiveMarketFeed(
        provider, "RELIANCE", config=_fast_config(interval=Interval.FIVE_MINUTE)
    )

    # RuntimeEngine.run takes Iterable[Candle]; it never learns that a
    # queue, a background thread, or a websocket were involved.
    engine.run(feed)

    assert engine.state.candles_processed > 0
    assert engine.state.error_count == 0
