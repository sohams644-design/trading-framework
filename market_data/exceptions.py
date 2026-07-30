"""Market-data specific exceptions."""


class InstrumentNotFoundError(LookupError):
    """Raised when a trading symbol or instrument token is unavailable."""


class CandleValidationError(ValueError):
    """Raised when historical candle data fails validation."""
