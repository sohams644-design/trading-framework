"""Backtesting entry point: replays history through the shared runtime loop."""

from __future__ import annotations

from domain.candle import Candle
from execution.order_manager import OrderManager
from execution.order_request_builder import OrderRequestBuilder
from execution.provider import ExecutionProvider
from indicators.context import IndicatorContext
from indicators.session import MarketSession
from portfolio.portfolio import Portfolio
from risk.risk_manager import RiskManager
from runtime.config import RuntimeConfig
from runtime.engine import RuntimeEngine
from strategies.base_strategy import BaseStrategy

from backtesting.replay import Replay


class BacktestEngine:
    """Runs a strategy over historical candles.

    The per-candle pipeline lives in ``RuntimeEngine``; this class only
    supplies backtest-appropriate configuration and a ``Replay`` feed, so
    backtesting and live running can never drift apart.

    Backtests run with ``continue_on_error=False``: a bad candle should fail
    loudly rather than be silently skipped, since silently skipping one
    would produce misleading results.
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
        session: MarketSession | None = None,
    ) -> None:
        self.portfolio = portfolio
        self.indicator_context = indicator_context
        self.runtime = RuntimeEngine(
            strategy=strategy,
            indicator_context=indicator_context,
            risk_manager=risk_manager,
            order_manager=order_manager,
            execution_provider=execution_provider,
            order_request_builder=order_request_builder,
            portfolio=portfolio,
            config=RuntimeConfig(
                session=session or MarketSession(),
                continue_on_error=False,
            ),
        )

    def run(self, candles: list[Candle]) -> None:
        """Replay every candle in order, updating the portfolio as it goes."""

        self.runtime.run(Replay(candles))
