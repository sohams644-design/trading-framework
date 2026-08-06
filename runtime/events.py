"""Lightweight runtime events.

This is deliberately not an event framework: no bus, no registry, no
dispatcher. It is a single optional callback the engine invokes at notable
points, so future consumers (dashboard, notifications, watchdog, metrics)
have an obvious place to listen without the engine knowing who cares.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any


class RuntimeEvent(Enum):
    """Notable points in a runtime execution."""

    RUNTIME_STARTED = "RUNTIME_STARTED"
    RUNTIME_STOPPED = "RUNTIME_STOPPED"
    RUNTIME_PAUSED = "RUNTIME_PAUSED"
    RUNTIME_RESUMED = "RUNTIME_RESUMED"
    CANDLE_RECEIVED = "CANDLE_RECEIVED"
    SESSION_ROLLED = "SESSION_ROLLED"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    TRADE_REJECTED = "TRADE_REJECTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    TRADE_CLOSED = "TRADE_CLOSED"
    ERROR_OCCURRED = "ERROR_OCCURRED"


# Payload keys vary by event (e.g. "candle", "signal", "decision", "order",
# "result", "trade", "stage", "error"). Kept as a plain mapping so adding a
# new event never requires a new type.
RuntimeEventCallback = Callable[[RuntimeEvent, dict[str, Any]], None]
