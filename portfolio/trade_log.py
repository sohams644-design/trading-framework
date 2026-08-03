"""Append-only log of completed trades."""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.trade_record import TradeRecord


@dataclass(slots=True)
class TradeLog:
    """Records completed trades in the order they closed."""

    _records: list[TradeRecord] = field(default_factory=list)

    def record(self, trade: TradeRecord) -> None:
        """Append a completed trade to the log."""

        self._records.append(trade)

    @property
    def records(self) -> list[TradeRecord]:
        """Return all recorded trades, in close order."""

        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)
