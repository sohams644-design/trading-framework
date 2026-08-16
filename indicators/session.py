"""Reusable market session helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True, slots=True)
class MarketSession:
    """Defines reusable intraday session boundaries."""

    market_open: time = time(9, 15)
    market_close: time = time(15, 30)
    opening_range_minutes: int = 15
    square_off_time: time = time(15, 15)

    def is_market_open(self, timestamp: datetime) -> bool:
        """Return whether a timestamp is inside the regular market session."""

        current_time = timestamp.time()
        return self.market_open <= current_time <= self.market_close

    def is_opening_range_active(self, timestamp: datetime) -> bool:
        """Return whether the timestamp is inside the opening range window."""

        start = self._datetime_for(timestamp, self.market_open)
        end = start + timedelta(minutes=self.opening_range_minutes)
        return start <= timestamp < end

    def is_opening_range_complete(self, timestamp: datetime) -> bool:
        """Return whether the opening range window has completed."""

        start = self._datetime_for(timestamp, self.market_open)
        return timestamp >= start + timedelta(minutes=self.opening_range_minutes)

    def is_square_off_time(self, timestamp: datetime) -> bool:
        """Return whether square-off rules should be active."""

        return timestamp.time() >= self.square_off_time

    def is_within_entry_window(self, timestamp: datetime, entry_window_minutes: int) -> bool:
        """Return whether new entries are still allowed for the session.

        The window opens when the opening range completes and closes
        ``entry_window_minutes`` later -- an ORB strategy has no business
        signaling a fresh breakout entry hours after the open, since the
        move it's meant to catch has typically already happened by then.
        """

        range_end = self._datetime_for(timestamp, self.market_open) + timedelta(
            minutes=self.opening_range_minutes
        )
        window_end = range_end + timedelta(minutes=entry_window_minutes)
        return timestamp < window_end

    def should_reset(self, previous: datetime | None, current: datetime) -> bool:
        """Return whether indicator state should reset for a new session."""

        if previous is None:
            return False
        return previous.date() != current.date() and self.is_market_open(current)

    @staticmethod
    def _datetime_for(timestamp: datetime, boundary: time) -> datetime:
        return datetime.combine(timestamp.date(), boundary, tzinfo=timestamp.tzinfo)
