"""Engine lifecycle state for a single runtime execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from domain.candle import Candle


class RuntimeStatus(Enum):
    """Lifecycle states a runtime engine can occupy."""

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


def _new_runtime_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass(slots=True)
class RuntimeState:
    """Tracks one running engine instance.

    This is engine lifecycle state, not financial state: cash, positions,
    and realized PnL belong to ``Portfolio``. ``runtime_id`` identifies one
    execution and lives here rather than in ``RuntimeConfig``, which
    describes immutable configuration rather than a running instance.
    """

    runtime_id: str = field(default_factory=_new_runtime_id)
    status: RuntimeStatus = RuntimeStatus.NOT_STARTED
    last_processed_candle: Candle | None = None
    current_session_date: date | None = None
    candles_processed: int = 0
    error_count: int = 0
    started_at: datetime | None = None
    stopped_at: datetime | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the engine is actively processing candles."""

        return self.status is RuntimeStatus.RUNNING

    @property
    def is_stopped(self) -> bool:
        """Return whether the engine has been stopped."""

        return self.status is RuntimeStatus.STOPPED
