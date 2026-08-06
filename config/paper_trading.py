"""Paper trading application configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from config.live_feed import LiveFeedConfig
from config.risk import RiskConfig


@dataclass(frozen=True, slots=True)
class PaperTradingConfig:
    """Application-level settings for one paper trading session.

    This carries the details no component config owns: which symbol and
    exchange to trade, and how much capital to start with. Component
    behaviour still comes from the existing configs it aggregates.

    ``continue_on_error`` defaults to True, the inverse of a backtest: a
    live session should survive a recoverable per-candle error and keep
    running, while a backtest should fail loudly rather than silently skip
    a candle and report misleading results.
    """

    symbol: str
    exchange: str = "NSE"
    starting_capital: float = 100_000.0
    live_feed: LiveFeedConfig = field(default_factory=LiveFeedConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    continue_on_error: bool = True
