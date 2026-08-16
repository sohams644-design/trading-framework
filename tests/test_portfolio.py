from datetime import datetime

import pytest

from domain.signal import Signal
from domain.trade import TradeDirection
from execution.execution_result import ExecutionResult, OrderStatus
from execution.order_request import OrderRequest, OrderType, Product
from performance.charges_calculator import ChargesCalculator
from portfolio.portfolio import Portfolio


def _order(symbol: str = "RELIANCE", side: TradeDirection = TradeDirection.BUY, quantity: int = 10) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        exchange="NSE",
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        product=Product.INTRADAY,
    )


def _filled(fill_price: float, timestamp: datetime = datetime(2026, 7, 30, 9, 30)) -> ExecutionResult:
    return ExecutionResult(
        success=True,
        status=OrderStatus.FILLED,
        timestamp=timestamp,
        broker_order_id="SIM-000001",
        fill_price=fill_price,
    )


def test_portfolio_opens_long_position_and_deducts_cash():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)

    portfolio.on_fill(_order(quantity=10), _filled(100.0), entry_signal)

    assert portfolio.cash == 99_000.0
    assert portfolio.positions["RELIANCE"].quantity == 10
    assert portfolio.positions["RELIANCE"].average_price == 100.0
    assert portfolio.trades_today == 1


def test_portfolio_opens_short_position_and_credits_cash():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.sell("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)

    portfolio.on_fill(_order(side=TradeDirection.SELL, quantity=10), _filled(100.0), entry_signal)

    assert portfolio.cash == 101_000.0
    assert portfolio.positions["RELIANCE"].quantity == -10


def test_portfolio_closes_long_position_records_trade_and_pnl():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    portfolio.on_fill(_order(quantity=10), _filled(100.0), entry_signal)

    exit_signal = Signal.exit_long(
        "RELIANCE", datetime(2026, 7, 30, 10, 0), price=105.0, reason="opposite_breakout_exit"
    )
    portfolio.on_fill(
        _order(side=TradeDirection.SELL, quantity=10),
        _filled(105.0, timestamp=datetime(2026, 7, 30, 10, 0)),
        exit_signal,
    )

    charges = ChargesCalculator().calculate_intraday(buy_price=100.0, sell_price=105.0, quantity=10)
    net_pnl = 50.0 - charges.total

    assert "RELIANCE" not in portfolio.positions
    assert portfolio.cash == pytest.approx(100_050.0 - charges.total)
    assert portfolio.realized_pnl == pytest.approx(net_pnl)
    assert len(portfolio.trade_log) == 1

    record = portfolio.trade_log.records[0]
    assert record.direction is TradeDirection.BUY
    assert record.entry_price == 100.0
    assert record.exit_price == 105.0
    assert record.quantity == 10
    assert record.pnl == pytest.approx(net_pnl)
    assert record.charges == charges.total
    assert record.reason == "opposite_breakout_exit"


def test_portfolio_closes_short_position_records_trade_and_pnl():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.sell("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    portfolio.on_fill(_order(side=TradeDirection.SELL, quantity=10), _filled(100.0), entry_signal)

    exit_signal = Signal.exit_short("RELIANCE", datetime(2026, 7, 30, 10, 0), price=95.0)
    portfolio.on_fill(
        _order(side=TradeDirection.BUY, quantity=10),
        _filled(95.0, timestamp=datetime(2026, 7, 30, 10, 0)),
        exit_signal,
    )

    # Short round-trips sell-then-buy: the entry (100) is the sell leg, the
    # exit (95) is the buy leg -- the reverse mapping of a long.
    charges = ChargesCalculator().calculate_intraday(buy_price=95.0, sell_price=100.0, quantity=10)
    net_pnl = 50.0 - charges.total

    assert portfolio.realized_pnl == pytest.approx(net_pnl)
    record = portfolio.trade_log.records[0]
    assert record.direction is TradeDirection.SELL
    assert record.pnl == pytest.approx(net_pnl)


def test_portfolio_tracks_daily_realized_loss_on_losing_trade():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    portfolio.on_fill(_order(quantity=10), _filled(100.0), entry_signal)

    exit_signal = Signal.exit_long("RELIANCE", datetime(2026, 7, 30, 10, 0), price=90.0)
    portfolio.on_fill(
        _order(side=TradeDirection.SELL, quantity=10),
        _filled(90.0, timestamp=datetime(2026, 7, 30, 10, 0)),
        exit_signal,
    )

    charges = ChargesCalculator().calculate_intraday(buy_price=100.0, sell_price=90.0, quantity=10)
    net_loss = 100.0 + charges.total

    assert portfolio.realized_pnl == pytest.approx(-net_loss)
    assert portfolio.daily_realized_loss == pytest.approx(net_loss)


def test_portfolio_on_fill_ignores_non_filled_results():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    rejected = ExecutionResult(
        success=False, status=OrderStatus.REJECTED, timestamp=datetime(2026, 7, 30, 9, 30)
    )

    portfolio.on_fill(_order(), rejected, entry_signal)

    assert portfolio.positions == {}
    assert portfolio.cash == 100_000.0


def test_portfolio_close_unknown_symbol_is_noop():
    portfolio = Portfolio(cash=100_000.0)
    exit_signal = Signal.exit_long("RELIANCE", datetime(2026, 7, 30, 10, 0), price=105.0)

    portfolio.on_fill(_order(side=TradeDirection.SELL), _filled(105.0), exit_signal)

    assert portfolio.trade_log.records == []
    assert portfolio.cash == 100_000.0


def test_portfolio_snapshot_reflects_open_positions_and_counters():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    portfolio.on_fill(_order(quantity=10), _filled(100.0), entry_signal)

    context = portfolio.snapshot(market_open=False, trading_enabled=False)

    assert context.capital == 99_000.0
    assert context.capital_deployed == 1_000.0
    assert context.open_positions == 1
    assert context.active_symbols == {"RELIANCE"}
    assert context.trades_today == 1
    assert context.market_open is False
    assert context.trading_enabled is False


def test_portfolio_on_fill_returns_none_when_opening_a_position():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)

    assert portfolio.on_fill(_order(quantity=10), _filled(100.0), entry_signal) is None


def test_portfolio_on_fill_returns_trade_record_when_closing_a_position():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    portfolio.on_fill(_order(quantity=10), _filled(100.0), entry_signal)

    exit_signal = Signal.exit_long("RELIANCE", datetime(2026, 7, 30, 10, 0), price=105.0)
    trade = portfolio.on_fill(
        _order(side=TradeDirection.SELL, quantity=10),
        _filled(105.0, timestamp=datetime(2026, 7, 30, 10, 0)),
        exit_signal,
    )

    charges = ChargesCalculator().calculate_intraday(buy_price=100.0, sell_price=105.0, quantity=10)
    assert trade is not None
    assert trade.pnl == pytest.approx(50.0 - charges.total)
    assert trade is portfolio.trade_log.records[0]


def test_portfolio_on_fill_returns_none_for_unfilled_result():
    portfolio = Portfolio(cash=100_000.0)
    entry_signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    rejected = ExecutionResult(
        success=False, status=OrderStatus.REJECTED, timestamp=datetime(2026, 7, 30, 9, 30)
    )

    assert portfolio.on_fill(_order(), rejected, entry_signal) is None


def test_portfolio_on_fill_returns_none_when_closing_unknown_symbol():
    portfolio = Portfolio(cash=100_000.0)
    exit_signal = Signal.exit_long("RELIANCE", datetime(2026, 7, 30, 10, 0), price=105.0)

    assert portfolio.on_fill(_order(side=TradeDirection.SELL), _filled(105.0), exit_signal) is None


def test_portfolio_reset_daily_counters_clears_loss_and_trade_count():
    portfolio = Portfolio(cash=100_000.0, daily_realized_loss=500.0, trades_today=3)

    portfolio.reset_daily_counters()

    assert portfolio.daily_realized_loss == 0.0
    assert portfolio.trades_today == 0
