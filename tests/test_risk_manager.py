from datetime import datetime

from config.risk import RiskConfig
from domain.risk_decision import RejectReason
from domain.signal import Signal
from risk.risk_context import RiskContext
from risk.risk_manager import RiskManager


def _context(**overrides) -> RiskContext:
    fields = dict(capital=100_000.0)
    fields.update(overrides)
    return RiskContext(**fields)


def test_risk_manager_approves_entry_signal_with_sized_quantity():
    manager = RiskManager(RiskConfig(capital_allocation_pct=0.1))
    signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)

    decision = manager.evaluate(signal, _context())

    assert decision.approved is True
    assert decision.quantity == 100
    assert decision.reason is None


def test_risk_manager_always_approves_exit_signals_without_sizing_or_checks():
    manager = RiskManager()
    signal = Signal.exit_long("RELIANCE", datetime(2026, 7, 30, 15, 0), price=105.0)
    context = _context(
        market_open=False,
        trading_enabled=False,
        trades_today=999,
        open_positions=999,
    )

    decision = manager.evaluate(signal, context)

    assert decision.approved is True
    assert decision.quantity == 0
    assert decision.reason is None


def test_risk_manager_rejects_hold_signal_as_invalid():
    manager = RiskManager()
    signal = Signal.none("RELIANCE", datetime(2026, 7, 30, 9, 30))

    decision = manager.evaluate(signal, _context())

    assert decision.approved is False
    assert decision.reason is RejectReason.INVALID_SIGNAL


def test_risk_manager_rejects_entry_signal_missing_price():
    manager = RiskManager()
    signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=None)

    decision = manager.evaluate(signal, _context())

    assert decision.approved is False
    assert decision.reason is RejectReason.INVALID_SIGNAL


def test_risk_manager_rejects_when_safety_check_fails_before_sizing():
    manager = RiskManager()
    signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    context = _context(market_open=False)

    decision = manager.evaluate(signal, context)

    assert decision.approved is False
    assert decision.reason is RejectReason.MARKET_CLOSED


def test_risk_manager_rejects_when_trade_limit_exceeded():
    manager = RiskManager(RiskConfig(max_trades_per_day=1))
    signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    context = _context(trades_today=1)

    decision = manager.evaluate(signal, context)

    assert decision.approved is False
    assert decision.reason is RejectReason.MAX_TRADES


def test_risk_manager_rejects_when_sized_quantity_is_zero():
    manager = RiskManager(RiskConfig(capital_allocation_pct=0.1))
    signal = Signal.buy("RELIANCE", datetime(2026, 7, 30, 9, 30), price=100.0)
    context = _context(capital=0.0)

    decision = manager.evaluate(signal, context)

    assert decision.approved is False
    assert decision.reason is RejectReason.INSUFFICIENT_CAPITAL
