"""Entry point: backtest one symbol over a historical date range.

Pure composition -- this script wires existing components together and adds
no logic of its own. It loads history through the existing market-data
provider and replays it through ``BacktestEngine``, which is itself a thin
wrapper over the same ``RuntimeEngine`` paper and live trading use.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from backtesting.engine import BacktestEngine
from backtesting.results import BacktestResults, Results
from broker.zerodha_auth import ZerodhaAuthenticator, ZerodhaAuthError
from config.orb import ORBStrategyConfig
from config.risk import RiskConfig
from domain.candle import Candle
from execution.order_manager import OrderManager
from execution.order_request_builder import OrderRequestBuilder
from execution.simulated_execution_provider import SimulatedExecutionProvider
from indicators.context import IndicatorContext
from indicators.session import MarketSession
from market_data.historical_loader import HistoricalDataLoader
from market_data.instrument_manager import InstrumentManager
from market_data.interval import Interval
from portfolio.portfolio import Portfolio
from risk.risk_manager import RiskManager
from strategies.orb import ORBStrategy
from version import __version__

logger = logging.getLogger("run_backtest")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest one symbol over a historical date range."
    )
    parser.add_argument("symbol", help="Trading symbol, e.g. RELIANCE")
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument(
        "--interval",
        default=Interval.FIVE_MINUTE.value,
        choices=[interval.value for interval in Interval],
    )
    parser.add_argument("--log-level", default="WARNING")
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.WARNING),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )


def load_candles(args: argparse.Namespace) -> list[Candle]:
    """Fetch validated history through the existing provider and loader."""

    authenticator = ZerodhaAuthenticator()
    access_token = authenticator.access_token()

    from broker.zerodha_market_data import ZerodhaMarketDataProvider

    provider = ZerodhaMarketDataProvider(
        instrument_manager=InstrumentManager(),
        kite_client=authenticator.kite_client(access_token),
    )
    return HistoricalDataLoader(provider).load(
        symbol=args.symbol.upper(),
        from_date=datetime.fromisoformat(args.from_date),
        to_date=datetime.fromisoformat(args.to_date),
        interval=Interval.from_value(args.interval),
    )


def build_engine(args: argparse.Namespace) -> tuple[BacktestEngine, Portfolio]:
    """Compose a backtest from existing framework components."""

    strategy_config = ORBStrategyConfig()
    execution_provider = SimulatedExecutionProvider()
    portfolio = Portfolio(cash=args.capital)

    engine = BacktestEngine(
        strategy=ORBStrategy(args.symbol.upper(), config=strategy_config),
        indicator_context=IndicatorContext.with_defaults(),
        risk_manager=RiskManager(RiskConfig()),
        order_manager=OrderManager(execution_provider),
        execution_provider=execution_provider,
        order_request_builder=OrderRequestBuilder(exchange=args.exchange.upper()),
        portfolio=portfolio,
        session=strategy_config.session,
    )
    return engine, portfolio


def print_banner(args: argparse.Namespace, candles: list[Candle]) -> None:
    """Announce the exact build and settings that produced this run.

    Deliberately ASCII: a rupee sign raises UnicodeEncodeError on consoles
    using cp1252, which would kill the process at startup.
    """

    sessions = len({candle.timestamp.date() for candle in candles})
    line = "=" * 62
    print(line)
    print(f" Trading Framework v{__version__}  |  BACKTEST (simulated fills)")
    print(line)
    print(" Strategy:    ORBStrategy")
    print(f" Symbol:      {args.symbol.upper()} ({args.exchange.upper()})")
    print(f" Range:       {args.from_date} .. {args.to_date}")
    print(f" Interval:    {args.interval}")
    print(f" Candles:     {len(candles)} over {sessions} sessions")
    print(f" Capital:     INR {args.capital:,.2f}")
    print(line)


def print_summary(
    results: BacktestResults, portfolio: Portfolio, engine: BacktestEngine
) -> None:
    """Report the run using the existing performance calculations."""

    print("\n--- Backtest summary ---")
    print(f"Candles:        {engine.runtime.state.candles_processed}")
    print(f"Errors:         {engine.runtime.state.error_count}")
    print(f"Trades:         {results.trade_count}")
    print(f"Win rate:       {results.win_rate:.1%}")
    print(f"Net PnL:        {results.net_pnl:.2f}")
    print(f"Average winner: {results.average_winner:.2f}")
    print(f"Average loser:  {results.average_loser:.2f}")
    print(f"Profit factor:  {results.profit_factor:.2f}")
    print(f"Max drawdown:   {results.max_drawdown:.2f}")
    print(f"Closing cash:   {portfolio.cash:.2f}")
    print("\nNote: fills are at candle close with no slippage, brokerage, or")
    print("taxes modelled, so net PnL is optimistic by construction.")

    for trade in portfolio.trade_log.records:
        print(
            f"  {trade.entry_time:%Y-%m-%d %H:%M}  {trade.direction.value:4}"
            f" {trade.quantity:>5} @ {trade.entry_price:.2f} -> {trade.exit_price:.2f}"
            f"  pnl {trade.pnl:>10.2f}  ({trade.reason})"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)

    try:
        candles = load_candles(args)
    except ZerodhaAuthError as error:
        print(f"Authentication failed: {error}", file=sys.stderr)
        return 1

    if not candles:
        print("No candles returned for that symbol and range.", file=sys.stderr)
        return 1

    print_banner(args, candles)

    engine, portfolio = build_engine(args)
    engine.run(candles)

    print_summary(Results().calculate(portfolio.trade_log), portfolio, engine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
