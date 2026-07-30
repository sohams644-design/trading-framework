"""Cached instrument lookup service."""

from __future__ import annotations

from market_data.exceptions import InstrumentNotFoundError
from domain.instrument import Instrument
from market_data.instrument_repository import CsvInstrumentRepository, InstrumentRepository


class InstrumentManager:
    """Caches repository instruments and provides fast symbol/token lookup."""

    def __init__(self, repository: InstrumentRepository | None = None) -> None:
        self.repository = repository or CsvInstrumentRepository()
        self._by_symbol: dict[str, Instrument] = {}
        self._by_token: dict[int, Instrument] = {}
        self._load_instruments()

    def get_by_symbol(self, symbol: str) -> Instrument:
        """Return instrument metadata for a trading symbol."""

        normalized_symbol = symbol.upper()
        try:
            return self._by_symbol[normalized_symbol]
        except KeyError as exc:
            raise InstrumentNotFoundError(
                f"Instrument symbol not found: {normalized_symbol}"
            ) from exc

    def get_by_token(self, instrument_token: int) -> Instrument:
        """Return instrument metadata for an instrument token."""

        try:
            return self._by_token[instrument_token]
        except KeyError as exc:
            raise InstrumentNotFoundError(
                f"Instrument token not found: {instrument_token}"
            ) from exc

    def get_token(self, symbol: str) -> int:
        """Return the instrument token for a trading symbol."""

        return self.get_by_symbol(symbol).instrument_token

    def _load_instruments(self) -> None:
        for instrument in self.repository.list_instruments():
            self._by_symbol[instrument.symbol] = instrument
            self._by_token[instrument.instrument_token] = instrument
