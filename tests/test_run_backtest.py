from datetime import datetime

import pytest

import run_backtest
from domain.candle import Candle
from market_data.interval import Interval


def test_parse_args_defaults():
    args = run_backtest.parse_args(
        ["reliance", "--from", "2026-05-01", "--to", "2026-06-01"]
    )

    assert args.symbol == "reliance"
    assert args.exchange == "NSE"
    assert args.capital == 100_000.0
    assert args.interval == Interval.FIVE_MINUTE.value


def test_parse_args_requires_a_date_range():
    with pytest.raises(SystemExit):
        run_backtest.parse_args(["RELIANCE"])


def test_parse_args_rejects_an_unsupported_interval():
    with pytest.raises(SystemExit):
        run_backtest.parse_args(
            [
                "RELIANCE",
                "--from",
                "2026-05-01",
                "--to",
                "2026-06-01",
                "--interval",
                "2hour",
            ]
        )


def _candle(
    hour: int,
    minute: int,
    high: float,
    low: float,
    close: float,
    volume: int,
) -> Candle:
    return Candle(
        timestamp=datetime(2026, 7, 30, hour, minute),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_build_engine_composes_a_backtest_that_trades():
    """The entry point wires real components; nothing is stubbed."""

    args = run_backtest.parse_args(
        [
            "reliance",
            "--from",
            "2026-07-30",
            "--to",
            "2026-07-30",
            "--capital",
            "75000",
        ]
    )

    engine, portfolio = run_backtest.build_engine(args)

    assert portfolio.cash == 75_000.0
    assert (
        type(engine.runtime.execution_provider).__name__
        == "SimulatedExecutionProvider"
    )
    assert engine.runtime.config.continue_on_error is False

    engine.run(_one_breakout_session())

    assert len(portfolio.trade_log) == 1
    assert portfolio.trade_log.records[0].reason == "stop_loss"


def _one_breakout_session() -> list[Candle]:
    """A session that warms every default indicator, then breaks out."""

    candles = [
        _candle(9, 15, high=101, low=90, close=99, volume=100),
        _candle(9, 20, high=102, low=91, close=100, volume=100),
    ]

    minute = 30

    for _ in range(6):
        candles.append(
            _candle(
                9 + minute // 60,
                minute % 60,
                high=100,
                low=98,
                close=99,
                volume=100,
            )
        )
        minute += 5

    candles.append(
        _candle(
            9 + minute // 60,
            minute % 60,
            high=110,
            low=103,
            close=108,
            volume=300,
        )
    )

    candles.append(
        _candle(
            15,
            15,
            high=110,
            low=100,
            close=106,
            volume=100,
        )
    )

    return candles


def test_main_reports_auth_failure_without_traceback(monkeypatch, capsys):
    from broker.zerodha_auth import ZerodhaAuthError

    def explode(_args):
        raise ZerodhaAuthError("API_KEY is not configured.")

    monkeypatch.setattr(run_backtest, "load_candles", explode)

    exit_code = run_backtest.main(
        ["RELIANCE", "--from", "2026-05-01", "--to", "2026-06-01"]
    )

    assert exit_code == 1
    assert "Authentication failed" in capsys.readouterr().err


def test_main_reports_an_empty_range_without_running(monkeypatch, capsys):
    monkeypatch.setattr(run_backtest, "load_candles", lambda _args: [])

    exit_code = run_backtest.main(
        ["RELIANCE", "--from", "2026-05-01", "--to", "2026-06-01"]
    )

    assert exit_code == 1
    assert "No candles returned" in capsys.readouterr().err


def test_print_banner_is_ascii_safe_for_cp1252_consoles():
    """A rupee sign here would crash startup on a cp1252 console."""

    import contextlib
    import io

    args = run_backtest.parse_args(
        ["RELIANCE", "--from", "2026-07-30", "--to", "2026-07-30"]
    )

    buffer = io.TextIOWrapper(
        io.BytesIO(),
        encoding="cp1252",
        errors="strict",
    )

    with contextlib.redirect_stdout(buffer):
        run_backtest.print_banner(
            args,
            [_candle(9, 15, 101, 90, 99, 100)],
        )

    buffer.flush()