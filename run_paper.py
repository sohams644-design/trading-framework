"""Entry point: paper-trade one symbol for one session.

Pure composition -- this script wires existing components together and adds
no logic of its own. Orders are simulated; nothing is ever sent to a broker.
"""

from __future__ import annotations

import argparse
import logging
import sys

from backtesting.results import Results
from broker.zerodha_auth import ZerodhaAuthenticator, ZerodhaAuthError
from broker.zerodha_market_data import ZerodhaMarketDataProvider
from config.live_feed import LiveFeedConfig
from config.orb import ORBStrategyConfig
from config.paper_trading import PaperTradingConfig
from config.risk import RiskConfig
from market_data.instrument_manager import InstrumentManager
from market_data.interval import Interval
from runtime.paper_trading import PaperTradingRunner
from strategies.orb import ORBStrategy
from version import __version__

logger = logging.getLogger("run_paper")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Paper-trade one symbol for one session.")
    parser.add_argument("symbol", help="Trading symbol, e.g. RELIANCE")
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument(
        "--interval",
        default=Interval.ONE_MINUTE.value,
        choices=[interval.value for interval in Interval],
        help="Candle interval to aggregate ticks into.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )


def build_runner(args: argparse.Namespace) -> PaperTradingRunner:
    """Compose a paper trading session from existing framework components."""

    authenticator = ZerodhaAuthenticator()
    access_token = authenticator.access_token()

    provider = ZerodhaMarketDataProvider(
        instrument_manager=InstrumentManager(),
        kite_client=authenticator.kite_client(access_token),
        ticker_client=authenticator.ticker_client(access_token),
    )

    config = PaperTradingConfig(
        symbol=args.symbol.upper(),
        exchange=args.exchange.upper(),
        starting_capital=args.capital,
        live_feed=LiveFeedConfig(interval=Interval.from_value(args.interval)),
        risk=RiskConfig(),
    )

    return PaperTradingRunner(
        provider=provider,
        strategy=ORBStrategy(config.symbol, config=ORBStrategyConfig()),
        config=config,
    )


def print_banner(runner: PaperTradingRunner) -> None:
    """Announce the exact build and settings that produced this session.

    Deliberately ASCII: a rupee sign raises UnicodeEncodeError on consoles
    using cp1252, which would kill the process at startup.
    """

    config = runner.config
    line = "=" * 62
    print(line)
    print(f" Trading Framework v{__version__}  |  PAPER TRADING (simulated fills)")
    print(line)
    print(f" Strategy:    {type(runner.strategy).__name__}")
    print(f" Symbol:      {config.symbol} ({config.exchange})")
    print(f" Interval:    {config.live_feed.interval.value}")
    print(f" Capital:     INR {config.starting_capital:,.2f}")
    print(f" Runtime ID:  {runner.state.runtime_id}")
    print(line)

    # Also recorded in the log stream, so archived logs stay traceable.
    logger.info(
        "Trading Framework v%s | paper trading | strategy=%s symbol=%s "
        "interval=%s capital=%.2f runtime_id=%s",
        __version__,
        type(runner.strategy).__name__,
        config.symbol,
        config.live_feed.interval.value,
        config.starting_capital,
        runner.state.runtime_id,
    )


def print_summary(runner: PaperTradingRunner) -> None:
    """Report the session using the existing performance calculations."""

    results = Results().calculate(runner.trade_log)
    print("\n--- Paper trading summary ---")
    print(f"Version:        v{__version__} (runtime {runner.state.runtime_id})")
    print(f"Symbol:         {runner.config.symbol}")
    print(f"Candles:        {runner.state.candles_processed}")
    print(f"Errors:         {runner.state.error_count}")
    print(f"Trades:         {results.trade_count}")
    print(f"Win rate:       {results.win_rate:.1%}")
    print(f"Net PnL:        {results.net_pnl:.2f}")
    print(f"Profit factor:  {results.profit_factor:.2f}")
    print(f"Max drawdown:   {results.max_drawdown:.2f}")
    print(f"Closing cash:   {runner.portfolio.cash:.2f}")

    for trade in runner.trade_log.records:
        print(
            f"  {trade.direction.value:4} {trade.quantity:>5} @ {trade.entry_price:.2f}"
            f" -> {trade.exit_price:.2f}  pnl {trade.pnl:>10.2f}  ({trade.reason})"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)

    try:
        runner = build_runner(args)
    except ZerodhaAuthError as error:
        print(f"Authentication failed: {error}", file=sys.stderr)
        return 1

    print_banner(runner)

    try:
        runner.run()
    except KeyboardInterrupt:
        print("\nInterrupted; stopping session.", file=sys.stderr)
        runner.stop()

    print_summary(runner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
