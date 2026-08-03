"""Owns the backtest loop, wiring every existing framework layer together."""

from __future__ import annotations

from datetime import datetime

from domain.candle import Candle
from domain.risk_decision import RiskDecision
from domain.signal import Signal
from execution.order_manager import OrderManager
from execution.order_request_builder import OrderRequestBuilder
from execution.simulated_execution_provider import SimulatedExecutionProvider
from indicators.context import IndicatorContext
from indicators.session import MarketSession
from portfolio.portfolio import Portfolio
from risk.risk_manager import RiskManager
from strategies.base_strategy import BaseStrategy

from backtesting.replay import Replay


class BacktestEngine:
    """Replays candles through Indicators, Strategy, Risk, and Execution.

    This class contains no rules of its own: it only owns the per-candle
    loop and the day-boundary reset that keeps multi-day indicator state
    (VWAP, Opening Range) from leaking across sessions.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        indicator_context: IndicatorContext,
        risk_manager: RiskManager,
        order_manager: OrderManager,
        execution_provider: SimulatedExecutionProvider,
        order_request_builder: OrderRequestBuilder,
        portfolio: Portfolio,
        session: MarketSession | None = None,
    ) -> None:
        self.strategy = strategy
        self.indicator_context = indicator_context
        self.risk_manager = risk_manager
        self.order_manager = order_manager
        self.execution_provider = execution_provider
        self.order_request_builder = order_request_builder
        self.portfolio = portfolio
        self.session = session or MarketSession()
        self._previous_timestamp: datetime | None = None

    def run(self, candles: list[Candle]) -> None:
        """Replay every candle in order, updating the portfolio as it goes."""

        for candle in Replay(candles):
            self._process_candle(candle)

    def _process_candle(self, candle: Candle) -> None:
        if self.session.should_reset(self._previous_timestamp, candle.timestamp):
            self.indicator_context.reset()
            self.portfolio.reset_daily_counters()
        self._previous_timestamp = candle.timestamp

        self.indicator_context.update(candle)
        self.execution_provider.advance(candle)

        signal = self.strategy.generate_signal(candle, self.indicator_context)
        if not (signal.is_entry or signal.is_exit):
            return

        risk_context = self.portfolio.snapshot()
        decision = self.risk_manager.evaluate(signal, risk_context)
        if not decision.approved:
            return

        quantity = self._resolve_quantity(signal, decision)
        if quantity <= 0:
            return

        order = self.order_request_builder.build(signal, decision, quantity=quantity)
        result = self.order_manager.submit_order(order)
        self.portfolio.on_fill(order, result, signal)

    def _resolve_quantity(self, signal: Signal, decision: RiskDecision) -> int:
        if signal.is_exit:
            position = self.portfolio.positions.get(signal.symbol)
            return abs(position.quantity) if position is not None else 0
        return decision.quantity
