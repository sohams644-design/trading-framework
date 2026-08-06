import pytest

import run_paper
from market_data.interval import Interval


def test_parse_args_defaults():
    args = run_paper.parse_args(["reliance"])

    assert args.symbol == "reliance"
    assert args.exchange == "NSE"
    assert args.capital == 100_000.0
    assert args.interval == Interval.ONE_MINUTE.value


def test_parse_args_accepts_overrides():
    args = run_paper.parse_args(
        ["INFY", "--exchange", "BSE", "--capital", "50000", "--interval", "5minute"]
    )

    assert args.symbol == "INFY"
    assert args.exchange == "BSE"
    assert args.capital == 50_000.0
    assert args.interval == "5minute"


def test_parse_args_rejects_an_unsupported_interval():
    with pytest.raises(SystemExit):
        run_paper.parse_args(["RELIANCE", "--interval", "2hour"])


def test_build_runner_composes_a_paper_session(monkeypatch):
    """The entry point wires real components; only the broker edge is faked."""

    class FakeAuthenticator:
        def __init__(self, *args, **kwargs):
            pass

        def access_token(self):
            return "token"

        def kite_client(self, access_token=None):
            return object()

        def ticker_client(self, access_token=None):
            return object()

    class FakeInstrumentManager:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(run_paper, "ZerodhaAuthenticator", FakeAuthenticator)
    monkeypatch.setattr(run_paper, "InstrumentManager", FakeInstrumentManager)

    runner = run_paper.build_runner(
        run_paper.parse_args(["reliance", "--capital", "75000", "--interval", "5minute"])
    )

    assert runner.config.symbol == "RELIANCE"
    assert runner.config.exchange == "NSE"
    assert runner.config.starting_capital == 75_000.0
    assert runner.config.live_feed.interval is Interval.FIVE_MINUTE
    assert runner.portfolio.cash == 75_000.0
    # Paper trading never reaches a broker: fills stay simulated.
    assert type(runner._engine.execution_provider).__name__ == "SimulatedExecutionProvider"


def test_main_reports_auth_failure_without_traceback(monkeypatch, capsys):
    from broker.zerodha_auth import ZerodhaAuthError

    def explode(_args):
        raise ZerodhaAuthError("API_KEY is not configured.")

    monkeypatch.setattr(run_paper, "build_runner", explode)

    exit_code = run_paper.main(["RELIANCE"])

    assert exit_code == 1
    assert "Authentication failed" in capsys.readouterr().err


def test_print_summary_uses_existing_performance_calculations(capsys):
    from datetime import datetime

    from domain.trade import TradeDirection
    from domain.trade_record import TradeRecord
    from portfolio.portfolio import Portfolio

    class FakeRunner:
        def __init__(self):
            self.portfolio = Portfolio(cash=100_500.0)
            self.portfolio.trade_log.record(
                TradeRecord(
                    symbol="RELIANCE",
                    direction=TradeDirection.BUY,
                    entry_price=100.0,
                    exit_price=105.0,
                    quantity=100,
                    pnl=500.0,
                    entry_time=datetime(2026, 8, 6, 9, 30),
                    exit_time=datetime(2026, 8, 6, 15, 15),
                    reason="end_of_day_exit",
                )
            )
            self.trade_log = self.portfolio.trade_log
            self.config = type("C", (), {"symbol": "RELIANCE"})()
            self.state = type("S", (), {"candles_processed": 375, "error_count": 0})()

    run_paper.print_summary(FakeRunner())

    output = capsys.readouterr().out
    assert "Trades:         1" in output
    assert "Win rate:       100.0%" in output
    assert "Net PnL:        500.00" in output
    assert "end_of_day_exit" in output
