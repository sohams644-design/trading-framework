from datetime import datetime
from pathlib import Path

import csv
import pytest

from market_data.exceptions import CandleValidationError, InstrumentNotFoundError
from market_data.historical_loader import HistoricalDataLoader
from market_data.instrument_manager import InstrumentManager
from market_data.instrument_repository import CsvInstrumentRepository
from market_data.interval import Interval
from market_data.provider import MarketDataProvider
from market_data.validator import CandleValidator
from domain.candle import Candle


class FakeProvider(MarketDataProvider):
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.calls: list[tuple[str, Interval]] = []

    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: Interval,
    ) -> list[Candle]:
        self.calls.append((symbol, interval))
        return self.candles

    def get_live_quote(self, symbol: str) -> list[Candle]:
        return self.candles

    def stream_ticks(self, symbols: list[str]):
        return iter(())


def _candle(timestamp: datetime) -> Candle:
    return Candle(
        timestamp=timestamp,
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        volume=1000,
    )


def test_instrument_manager_uses_cached_symbol_and_token_lookup(tmp_path, monkeypatch):
    instrument_file = tmp_path / "instruments.csv"
    _write_instrument_file(
        instrument_file,
        [
            {
                "instrument_token": 123,
                "tradingsymbol": "RELIANCE",
                "exchange": "NSE",
                "name": "Reliance Industries",
            }
        ],
    )

    open_calls = 0
    original_open = Path.open

    def counted_open(self, *args, **kwargs):
        nonlocal open_calls
        if self == instrument_file:
            open_calls += 1
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)

    manager = InstrumentManager(CsvInstrumentRepository(instrument_file))

    assert manager.get_token("reliance") == 123
    assert manager.get_by_token(123).symbol == "RELIANCE"
    assert open_calls == 1


def test_instrument_manager_raises_meaningful_missing_symbol_error(tmp_path):
    instrument_file = tmp_path / "instruments.csv"
    _write_instrument_file(
        instrument_file,
        [{"instrument_token": 123, "tradingsymbol": "RELIANCE"}],
    )

    manager = InstrumentManager(CsvInstrumentRepository(instrument_file))

    with pytest.raises(InstrumentNotFoundError, match="Instrument symbol not found"):
        manager.get_by_symbol("INFY")


def test_historical_loader_retrieves_and_validates_candles():
    candle = _candle(datetime(2026, 7, 30, 9, 15))
    provider = FakeProvider([candle])
    loader = HistoricalDataLoader(provider)

    result = loader.load(
        "RELIANCE",
        datetime(2026, 7, 30, 9, 15),
        datetime(2026, 7, 30, 15, 30),
        Interval.FIVE_MINUTE,
    )

    assert result == [candle]
    assert provider.calls == [("RELIANCE", Interval.FIVE_MINUTE)]


@pytest.mark.parametrize(
    ("bad_candle", "message"),
    [
        (
            Candle(datetime(2026, 7, 30, 9, 15), 100, 90, 95, 98, 1000),
            "high is below low",
        ),
        (
            Candle(datetime(2026, 7, 30, 9, 15), 110, 105, 95, 100, 1000),
            "open is outside high/low",
        ),
        (
            Candle(datetime(2026, 7, 30, 9, 15), 100, 105, 95, 110, 1000),
            "close is outside high/low",
        ),
        (
            Candle(datetime(2026, 7, 30, 9, 15), 100, 105, 95, 100, -1),
            "volume is negative",
        ),
    ],
)
def test_candle_validator_rejects_invalid_candles(bad_candle, message):
    validator = CandleValidator()

    with pytest.raises(CandleValidationError, match=message):
        validator.validate([bad_candle])


def test_candle_validator_rejects_duplicate_timestamps():
    timestamp = datetime(2026, 7, 30, 9, 15)
    validator = CandleValidator()

    with pytest.raises(CandleValidationError, match="Duplicate candle timestamp"):
        validator.validate([_candle(timestamp), _candle(timestamp)])


def test_interval_enum_values_and_lookup():
    assert Interval.ONE_MINUTE.value == "minute"
    assert Interval.THREE_MINUTE.value == "3minute"
    assert Interval.FIVE_MINUTE.value == "5minute"
    assert Interval.FIFTEEN_MINUTE.value == "15minute"
    assert Interval.DAY.value == "day"
    assert Interval.from_value("5minute") is Interval.FIVE_MINUTE

    with pytest.raises(ValueError, match="Unsupported interval"):
        Interval.from_value("2hour")


def _write_instrument_file(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
