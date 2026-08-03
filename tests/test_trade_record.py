from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from domain.trade import TradeDirection
from domain.trade_record import TradeRecord


def test_trade_record_is_immutable():
    record = TradeRecord(
        symbol="RELIANCE",
        direction=TradeDirection.BUY,
        entry_price=100.0,
        exit_price=105.0,
        quantity=10,
        pnl=50.0,
        entry_time=datetime(2026, 7, 30, 9, 30),
        exit_time=datetime(2026, 7, 30, 10, 0),
    )

    with pytest.raises(FrozenInstanceError):
        record.pnl = 0.0


def test_trade_record_carries_reason_when_given():
    record = TradeRecord(
        symbol="RELIANCE",
        direction=TradeDirection.SELL,
        entry_price=100.0,
        exit_price=95.0,
        quantity=10,
        pnl=50.0,
        entry_time=datetime(2026, 7, 30, 9, 30),
        exit_time=datetime(2026, 7, 30, 15, 15),
        reason="end_of_day_exit",
    )

    assert record.reason == "end_of_day_exit"
