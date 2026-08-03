from datetime import datetime

from config.orb import ORBStrategyConfig
from config.risk import RiskConfig
from domain.candle import Candle
from domain.trade import TradeDirection
from domain.trade_record import TradeRecord
from execution.order_manager import OrderManager
from execution.order_request_builder import OrderRequestBuilder
from execution.simulated_execution_provider import SimulatedExecutionProvider
from indicators.context import IndicatorContext
from indicators.opening_range import OpeningRange
from indicators.relative_volume import RelativeVolume
from indicators.vwap import VWAP
from portfolio.portfolio import Portfolio
from risk.risk_manager import RiskManager
from strategies.orb import ORBStrategy

from backtesting.engine import BacktestEngine
from backtesting.replay import Replay
from backtesting.results import BacktestResults, Results


def _candle(date, hour: int, minute: int, high: float, low: float, close: float, volume: int) -> Candle:
    return Candle(
        timestamp=datetime(date.year, date.month, date.day, hour, minute),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


# --- Replay ---


def test_replay_yields_candles_in_order():
    candles = [
        _candle(datetime(2026, 7, 30), 9, 15, 101, 90, 99, 100),
        _candle(datetime(2026, 7, 30), 9, 20, 102, 91, 100, 100),
    ]

    assert list(Replay(candles)) == candles


# --- BacktestEngine: multi-day correctness ---


def _build_engine() -> tuple[BacktestEngine, Portfolio]:
    indicator_context = IndicatorContext()
    indicator_context.register("vwap", VWAP())
    indicator_context.register("opening_range", OpeningRange())
    indicator_context.register("relative_volume", RelativeVolume(lookback_period=2))

    strategy = ORBStrategy("RELIANCE", config=ORBStrategyConfig())
    risk_manager = RiskManager(RiskConfig())
    execution_provider = SimulatedExecutionProvider()
    order_manager = OrderManager(execution_provider)
    order_request_builder = OrderRequestBuilder(exchange="NSE")
    portfolio = Portfolio(cash=100_000.0)

    engine = BacktestEngine(
        strategy=strategy,
        indicator_context=indicator_context,
        risk_manager=risk_manager,
        order_manager=order_manager,
        execution_provider=execution_provider,
        order_request_builder=order_request_builder,
        portfolio=portfolio,
    )
    return engine, portfolio


def test_backtest_engine_resets_indicators_across_days_and_trades_both_days():
    engine, portfolio = _build_engine()
    day1 = datetime(2026, 7, 30)
    day2 = datetime(2026, 7, 31)

    day1_candles = [
        _candle(day1, 9, 15, high=101, low=90, close=99, volume=100),
        _candle(day1, 9, 20, high=102, low=91, close=100, volume=100),
        _candle(day1, 9, 30, high=110, low=103, close=108, volume=300),
        _candle(day1, 15, 15, high=110, low=100, close=106, volume=100),
    ]
    engine.run(day1_candles)

    assert len(portfolio.trade_log) == 1
    first_trade = portfolio.trade_log.records[0]
    assert first_trade.direction is TradeDirection.BUY
    assert first_trade.reason == "end_of_day_exit"

    # Day 1's opening range high (102) would contaminate day 2's if the
    # engine failed to reset IndicatorContext at the session boundary.
    day2_building_candles = [
        _candle(day2, 9, 15, high=95, low=85, close=90, volume=100),
        _candle(day2, 9, 20, high=96, low=86, close=91, volume=100),
    ]
    engine.run(day2_building_candles)

    assert engine.indicator_context.opening_range.opening_high == 96.0

    day2_remaining_candles = [
        # 100 breaks day 2's own opening high (96) but not day 1's stale 102 --
        # this only breaks out if the reset actually happened.
        _candle(day2, 9, 30, high=100, low=94, close=99, volume=250),
        _candle(day2, 15, 15, high=105, low=95, close=97, volume=100),
    ]
    engine.run(day2_remaining_candles)

    assert len(portfolio.trade_log) == 2
    second_trade = portfolio.trade_log.records[1]
    assert second_trade.direction is TradeDirection.BUY
    assert second_trade.reason == "end_of_day_exit"
    assert second_trade.entry_time.date() == day2.date()


def test_backtest_engine_skips_hold_signals_without_calling_risk_or_execution():
    engine, portfolio = _build_engine()
    day1 = datetime(2026, 7, 30)

    inside_range_only = [
        _candle(day1, 9, 15, high=101, low=90, close=99, volume=100),
    ]
    engine.run(inside_range_only)

    assert portfolio.trade_log.records == []
    assert portfolio.positions == {}


# --- Results ---


def _trade(pnl: float) -> TradeRecord:
    return TradeRecord(
        symbol="RELIANCE",
        direction=TradeDirection.BUY,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        quantity=1,
        pnl=pnl,
        entry_time=datetime(2026, 7, 30, 9, 30),
        exit_time=datetime(2026, 7, 30, 10, 0),
    )


def test_results_calculates_summary_statistics_from_trade_log():
    from portfolio.trade_log import TradeLog

    trade_log = TradeLog()
    trade_log.record(_trade(100.0))
    trade_log.record(_trade(-40.0))

    results = Results().calculate(trade_log)

    assert results == BacktestResults(
        trade_count=2,
        win_rate=0.5,
        net_pnl=60.0,
        average_winner=100.0,
        average_loser=-40.0,
        profit_factor=2.5,
        max_drawdown=40.0,
    )
