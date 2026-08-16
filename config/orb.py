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
<<<<<<< Updated upstream
    risk_reward_ratio: float = 2.0

    # Only take a fresh breakout entry within this many minutes of the
    # opening range completing -- an ORB edge decays through the session;
    # entries hours later are chasing a different move, not this one.
    entry_window_minutes: int = 45

    # ATR (intraday, resets every session like every other indicator here --
    # this is NOT the classic multi-day ATR) drives breakout confirmation,
    # stop placement, and the trailing stop.
    atr_period: int = 7

    # Require the close to clear the opening range by this many ATRs, not
    # just tick above it, so a single noisy wick can't count as a breakout.
    breakout_confirmation_atr_multiplier: float = 0.15

    # Stop is the TIGHTER of the opening-range extreme and entry -/+ this
    # many ATRs, so one unusually wide 15-minute range can't force an
    # oversized loss on a single trade.
    stop_atr_multiplier: float = 1.5

    # Once a trade is ahead by this many multiples of its initial risk, the
    # stop starts trailing instead of sitting fixed.
    trailing_activation_r: float = 1.0

    # Once trailing is active, the stop trails this many ATRs behind the
    # trade's running high/low-water mark, ratcheting only in its favor.
    trailing_atr_multiplier: float = 1.0

=======
    risk_reward_ratio: float = 1.0
>>>>>>> Stashed changes
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
