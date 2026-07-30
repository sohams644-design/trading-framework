"""Instrument domain model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Instrument:
    """Tradable instrument metadata needed for market-data lookup."""

    symbol: str
    instrument_token: int
    exchange: str | None = None
    name: str | None = None
