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

    use_stop_loss: bool = True
    use_profit_target: bool = True

    risk_reward_ratio: float = 2.0

    entry_window_minutes: int = 45
    atr_period: int = 7
    breakout_confirmation_atr_multiplier: float = 0.15
    stop_atr_multiplier: float = 1.5
    trailing_activation_r: float = 1.0
    trailing_atr_multiplier: float = 1.0

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