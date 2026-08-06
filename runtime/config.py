"""Immutable runtime engine configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from indicators.session import MarketSession


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Describes how a runtime engine behaves.

    This is immutable configuration only. Metadata about a specific running
    instance (its id, status, progress) belongs to ``RuntimeState``.

    ``continue_on_error`` separates two fundamentally different operating
    modes: a live engine should survive a recoverable per-candle error and
    keep running, while a backtest should fail loudly rather than silently
    skip a bad candle and report misleading results.
    """

    session: MarketSession = field(default_factory=MarketSession)
    continue_on_error: bool = True
