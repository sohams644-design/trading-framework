"""Historical candle validation utilities."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from market_data.exceptions import CandleValidationError
from domain.candle import Candle


class CandleValidator:
    """Validates structural correctness of historical candles."""

    def validate(self, candles: Iterable[Candle]) -> list[Candle]:
        """Validate candles and return them as a list."""

        validated_candles = list(candles)
        self._validate_duplicate_timestamps(validated_candles)

        for candle in validated_candles:
            self._validate_price_range(candle)
            self._validate_volume(candle)

        return validated_candles

    @staticmethod
    def _validate_duplicate_timestamps(candles: list[Candle]) -> None:
        seen: set[datetime] = set()
        for candle in candles:
            if candle.timestamp in seen:
                raise CandleValidationError(
                    f"Duplicate candle timestamp detected: {candle.timestamp.isoformat()}"
                )
            seen.add(candle.timestamp)

    @staticmethod
    def _validate_price_range(candle: Candle) -> None:
        if candle.high < candle.low:
            raise CandleValidationError(
                f"Candle high is below low at {candle.timestamp.isoformat()}"
            )

        if not candle.low <= candle.open <= candle.high:
            raise CandleValidationError(
                f"Candle open is outside high/low at {candle.timestamp.isoformat()}"
            )

        if not candle.low <= candle.close <= candle.high:
            raise CandleValidationError(
                f"Candle close is outside high/low at {candle.timestamp.isoformat()}"
            )

    @staticmethod
    def _validate_volume(candle: Candle) -> None:
        if candle.volume < 0:
            raise CandleValidationError(
                f"Candle volume is negative at {candle.timestamp.isoformat()}"
            )
