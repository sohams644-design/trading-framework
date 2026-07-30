"""Opening Range Breakout strategy configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from indicators.session import MarketSession


@dataclass(frozen=True, slots=True)
class ORBStrategyConfig:
    """Configurable ORB strategy parameters."""

    opening_range_minutes: int = 15
    relative_volume_threshold: float = 2.0
    allow_short: bool = True
    allow_long: bool = True
    exit_at_market_close: bool = True
    exit_on_opposite_breakout: bool = False
    session: MarketSession = field(default_factory=MarketSession)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "session",
            MarketSession(
                market_open=self.session.market_open,
                market_close=self.session.market_close,
                opening_range_minutes=self.opening_range_minutes,
                square_off_time=self.session.square_off_time,
            ),
        )
