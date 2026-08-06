"""Paper trading: a composition of existing components, not a new engine."""

from __future__ import annotations

import logging

from config.paper_trading import PaperTradingConfig
from execution.order_manager import OrderManager
from execution.order_request_builder import OrderRequestBuilder
from execution.simulated_execution_provider import SimulatedExecutionProvider
from indicators.context import IndicatorContext
from market_data.live_feed import LiveMarketFeed
from market_data.provider import MarketDataProvider
from portfolio.portfolio import Portfolio
from portfolio.trade_log import TradeLog
from risk.risk_manager import RiskManager
from runtime.config import RuntimeConfig
from runtime.engine import RuntimeEngine
from runtime.events import RuntimeEventCallback
from state.runtime_state import RuntimeState
from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class PaperTradingRunner:
    """Runs a strategy against live market data with simulated fills.

    This class trades nothing itself: it has no positions, no PnL, no risk
    rules, and no knowledge of any strategy. It assembles components that
    already exist and owns their shared lifecycle.

    Two things justify it over inline wiring. It guarantees that the *same*
    ``SimulatedExecutionProvider`` instance reaches both the ``OrderManager``
    and the ``RuntimeEngine`` — passing two would leave one armed with prices
    and the other placing orders, failing on the first trade. And it stops
    the engine and the feed together, rather than relying on generator
    finalisation to tear down the feed's background thread.

    Becoming live trading means swapping ``SimulatedExecutionProvider`` for
    ``ZerodhaExecutionProvider``. Nothing upstream changes.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        strategy: BaseStrategy,
        config: PaperTradingConfig,
        indicator_context: IndicatorContext | None = None,
        portfolio: Portfolio | None = None,
        on_event: RuntimeEventCallback | None = None,
    ) -> None:
        self.config = config
        self._portfolio = portfolio or Portfolio(cash=config.starting_capital)
        self._execution_provider = SimulatedExecutionProvider()
        self._feed = LiveMarketFeed(provider, config.symbol, config=config.live_feed)
        self._engine = RuntimeEngine(
            strategy=strategy,
            indicator_context=indicator_context or IndicatorContext.with_defaults(),
            risk_manager=RiskManager(config.risk),
            order_manager=OrderManager(self._execution_provider),
            execution_provider=self._execution_provider,
            order_request_builder=OrderRequestBuilder(exchange=config.exchange),
            portfolio=self._portfolio,
            config=RuntimeConfig(
                session=config.live_feed.session,
                continue_on_error=config.continue_on_error,
            ),
            on_event=on_event,
        )

    def run(self) -> None:
        """Trade the live feed until the session ends or ``stop`` is called."""

        logger.info(
            "Paper trading session started for %s on %s with capital %.2f.",
            self.config.symbol,
            self.config.exchange,
            self.config.starting_capital,
        )
        try:
            self._engine.run(self._feed)
        finally:
            self._feed.stop()
            logger.info(
                "Paper trading session finished for %s: %d candles, %d trades, "
                "realized pnl %.2f, %d errors.",
                self.config.symbol,
                self._engine.state.candles_processed,
                len(self._portfolio.trade_log),
                self._portfolio.realized_pnl,
                self._engine.state.error_count,
            )

    def stop(self) -> None:
        """Request a graceful shutdown of both the engine and the feed."""

        self._engine.stop()
        self._feed.stop()

    @property
    def strategy(self) -> BaseStrategy:
        """Return the strategy this session is running."""

        return self._engine.strategy

    @property
    def portfolio(self) -> Portfolio:
        """Return the portfolio this session is trading."""

        return self._portfolio

    @property
    def trade_log(self) -> TradeLog:
        """Return completed trades, for the caller to run analytics over."""

        return self._portfolio.trade_log

    @property
    def state(self) -> RuntimeState:
        """Return the engine's lifecycle state."""

        return self._engine.state
