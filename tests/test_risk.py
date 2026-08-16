from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from config.risk import RiskConfig
from domain.risk_decision import RejectReason, RiskDecision
from domain.signal import Signal
from risk.position_sizer import PositionSizer
from risk.risk_context import RiskContext
from risk.safety_checks import SafetyChecks
from risk.trade_limits import TradeLimits


def _entry_signal(symbol: str = "RELIANCE", price: float = 100.0) -> Signal:
    return Signal.buy(symbol, datetime(2026, 7, 30, 9, 30), price)


def _context(**overrides) -> RiskContext:
    fields = dict(capital=100_000.0)
    fields.update(overrides)
    return RiskContext(**fields)


# --- RiskDecision ---


def test_risk_decision_is_immutable():
    decision = RiskDecision.approved_entry(10)
    with pytest.raises(FrozenInstanceError):
        decision.approved = False


def test_risk_decision_approved_entry_carries_quantity():
    decision = RiskDecision.approved_entry(42)

    assert decision.approved is True
    assert decision.quantity == 42
    assert decision.reason is None


def test_risk_decision_approved_exit_has_zero_quantity_and_default_message():
    decision = RiskDecision.approved_exit()

    assert decision.approved is True
    assert decision.quantity == 0
    assert decision.reason is None
    assert decision.message == "Exit signals bypass risk gating."


def test_risk_decision_rejected_carries_reason_and_message():
    decision = RiskDecision.rejected(RejectReason.MARKET_CLOSED, "NSE session has ended.")

    assert decision.approved is False
    assert decision.quantity == 0
    assert decision.reason is RejectReason.MARKET_CLOSED
    assert decision.message == "NSE session has ended."


def test_reject_reason_enum_has_expected_values():
    assert {reason.value for reason in RejectReason} == {
        "DAILY_LOSS_LIMIT",
        "MAX_TRADES",
        "INVALID_SIGNAL",
        "INSUFFICIENT_CAPITAL",
        "POSITION_LIMIT",
        "POSITION_ALREADY_OPEN",
        "MARKET_CLOSED",
        "SAFETY_CHECK_FAILED",
    }


# --- SafetyChecks ---


def test_safety_checks_passes_when_all_conditions_are_met():
    result = SafetyChecks().evaluate(_entry_signal(), _context(), RiskConfig())

    assert result is None


def test_safety_checks_rejects_when_market_closed():
    reason, message = SafetyChecks().evaluate(
        _entry_signal(), _context(market_open=False), RiskConfig()
    )

    assert reason is RejectReason.MARKET_CLOSED
    assert "closed" in message


def test_safety_checks_rejects_when_trading_disabled():
    reason, message = SafetyChecks().evaluate(
        _entry_signal(), _context(trading_enabled=False), RiskConfig()
    )

    assert reason is RejectReason.SAFETY_CHECK_FAILED
    assert "disabled" in message


def test_safety_checks_rejects_symbol_not_in_allowlist():
    config = RiskConfig(allowed_symbols=frozenset({"INFY"}))

    reason, message = SafetyChecks().evaluate(_entry_signal("RELIANCE"), _context(), config)

    assert reason is RejectReason.SAFETY_CHECK_FAILED
    assert "RELIANCE" in message


def test_safety_checks_rejects_symbol_with_position_already_open():
    context = _context(active_symbols={"RELIANCE"})

    reason, message = SafetyChecks().evaluate(_entry_signal("RELIANCE"), context, RiskConfig())

    assert reason is RejectReason.POSITION_ALREADY_OPEN
    assert "RELIANCE" in message


# --- TradeLimits ---


def test_trade_limits_passes_within_all_limits():
    result = TradeLimits().evaluate(_entry_signal(), _context(), RiskConfig())

    assert result is None


def test_trade_limits_rejects_at_max_trades_per_day():
    config = RiskConfig(max_trades_per_day=3)
    context = _context(trades_today=3)

    reason, _ = TradeLimits().evaluate(_entry_signal(), context, config)

    assert reason is RejectReason.MAX_TRADES


def test_trade_limits_rejects_at_max_concurrent_positions():
    config = RiskConfig(max_concurrent_positions=2)
    context = _context(open_positions=2)

    reason, _ = TradeLimits().evaluate(_entry_signal(), context, config)

    assert reason is RejectReason.POSITION_LIMIT


def test_trade_limits_rejects_at_daily_loss_limit():
    config = RiskConfig(daily_loss_limit=1000.0)
    context = _context(daily_realized_loss=1000.0)

    reason, _ = TradeLimits().evaluate(_entry_signal(), context, config)

    assert reason is RejectReason.DAILY_LOSS_LIMIT


def test_trade_limits_rejects_at_max_capital_exposure():
    config = RiskConfig(max_capital_exposure=50_000.0)
    context = _context(capital_deployed=50_000.0)

    reason, _ = TradeLimits().evaluate(_entry_signal(), context, config)

    assert reason is RejectReason.INSUFFICIENT_CAPITAL


# --- PositionSizer ---


def test_position_sizer_computes_quantity_from_capital_allocation():
    sizer = PositionSizer()

    assert sizer.calculate_quantity(capital=100_000.0, entry_price=100.0, capital_allocation_pct=0.1) == 100


@pytest.mark.parametrize(
    ("capital", "entry_price", "capital_allocation_pct"),
    [
        (0.0, 100.0, 0.1),
        (100_000.0, 0.0, 0.1),
        (100_000.0, 100.0, 0.0),
        (-1000.0, 100.0, 0.1),
    ],
)
def test_position_sizer_returns_zero_for_invalid_inputs(capital, entry_price, capital_allocation_pct):
    sizer = PositionSizer()

    assert sizer.calculate_quantity(capital, entry_price, capital_allocation_pct) == 0


def test_position_sizer_by_risk_sizes_to_the_configured_risk_budget():
    sizer = PositionSizer()

    # Risk budget = 100_000 * 0.01 = 1_000. Risk per share = |100 - 95| = 5.
    # 1_000 / 5 = 200 shares.
    quantity = sizer.calculate_quantity_by_risk(
        capital=100_000.0, entry_price=100.0, stop_loss=95.0, risk_per_trade_pct=0.01
    )

    assert quantity == 200


def test_position_sizer_by_risk_gives_a_tighter_stop_a_larger_position():
    sizer = PositionSizer()

    tight_stop_qty = sizer.calculate_quantity_by_risk(
        capital=100_000.0, entry_price=100.0, stop_loss=99.0, risk_per_trade_pct=0.01
    )
    wide_stop_qty = sizer.calculate_quantity_by_risk(
        capital=100_000.0, entry_price=100.0, stop_loss=90.0, risk_per_trade_pct=0.01
    )

    assert tight_stop_qty > wide_stop_qty


def test_position_sizer_by_risk_is_capped_by_max_capital_allocation():
    sizer = PositionSizer()

    # A 1-rupee stop would otherwise demand 1_000 shares (1_000/1), well
    # beyond what 10% of capital at price 100 can actually buy (100 shares).
    quantity = sizer.calculate_quantity_by_risk(
        capital=100_000.0,
        entry_price=100.0,
        stop_loss=99.0,
        risk_per_trade_pct=0.01,
        max_capital_allocation_pct=0.1,
    )

    assert quantity == 100


@pytest.mark.parametrize(
    ("capital", "entry_price", "stop_loss", "risk_per_trade_pct"),
    [
        (0.0, 100.0, 95.0, 0.01),
        (100_000.0, 0.0, 95.0, 0.01),
        (100_000.0, 100.0, 100.0, 0.01),  # zero risk per share
        (100_000.0, 100.0, 95.0, 0.0),
    ],
)
def test_position_sizer_by_risk_returns_zero_for_invalid_inputs(
    capital, entry_price, stop_loss, risk_per_trade_pct
):
    sizer = PositionSizer()

    assert sizer.calculate_quantity_by_risk(capital, entry_price, stop_loss, risk_per_trade_pct) == 0
