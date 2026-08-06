"""Market-data abstractions and services."""

from market_data.exceptions import CandleValidationError, InstrumentNotFoundError
from market_data.historical_loader import HistoricalDataLoader
from domain.instrument import Instrument
from market_data.instrument_manager import InstrumentManager
from market_data.instrument_repository import CsvInstrumentRepository, InstrumentRepository
from market_data.interval import Interval
from market_data.provider import MarketDataProvider
from market_data.tick_aggregator import TickAggregator
from market_data.validator import CandleValidator

# LiveMarketFeed is deliberately not re-exported here. It depends on
# config.LiveFeedConfig, which in turn depends on market_data.Interval, so
# re-exporting either from its package __init__ makes `import config` and
# `import market_data` mutually recursive. Import it from its module:
#     from market_data.live_feed import LiveMarketFeed

__all__ = [
    "CandleValidationError",
    "CandleValidator",
    "CsvInstrumentRepository",
    "HistoricalDataLoader",
    "Instrument",
    "InstrumentManager",
    "InstrumentNotFoundError",
    "InstrumentRepository",
    "Interval",
    "MarketDataProvider",
    "TickAggregator",
]
