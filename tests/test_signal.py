from datetime import datetime

from domain.signal import Signal, SignalAction


def test_signal_entry_flag_for_directional_actions():
    signal = Signal(
        symbol="RELIANCE",
        action=SignalAction.BUY,
        timestamp=datetime(2026, 7, 30, 9, 15),
    )

    assert signal.is_entry is True


def test_signal_entry_flag_for_hold_action():
    signal = Signal(
        symbol="RELIANCE",
        action=SignalAction.HOLD,
        timestamp=datetime(2026, 7, 30, 9, 15),
    )

    assert signal.is_entry is False
