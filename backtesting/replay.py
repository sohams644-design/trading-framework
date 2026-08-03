"""Deterministic historical-candle replay."""

from __future__ import annotations

from collections.abc import Iterator

from domain.candle import Candle


class Replay:
    """Yields historical candles one at a time, in order. Nothing else.

    Replay does no calculation of its own: no indicators, no strategy, no
    fills. It only walks history in the order given, exactly the way live
    trading will eventually walk a live feed.
    """

    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    def __iter__(self) -> Iterator[Candle]:
        return iter(self.candles)
