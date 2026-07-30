"""Instrument repository abstractions and CSV implementation."""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from config import settings
from domain.instrument import Instrument


class InstrumentRepository(ABC):
    """Source of instrument metadata for InstrumentManager."""

    @abstractmethod
    def list_instruments(self) -> Iterable[Instrument]:
        """Return all known instruments from the backing store."""
        raise NotImplementedError


class CsvInstrumentRepository(InstrumentRepository):
    """Loads instruments from a CSV file."""

    def __init__(self, instrument_file: str | Path = settings.instrument_file) -> None:
        self.instrument_file = Path(instrument_file)

    def list_instruments(self) -> Iterable[Instrument]:
        """Yield instruments from the configured CSV file."""

        with self.instrument_file.open(newline="") as instrument_stream:
            reader = csv.DictReader(instrument_stream)
            self._validate_columns(reader.fieldnames)
            for row in reader:
                yield self._build_instrument(row)

    @staticmethod
    def _validate_columns(fieldnames: list[str] | None) -> None:
        required_columns = {"instrument_token", "tradingsymbol"}
        missing_columns = required_columns - set(fieldnames or [])

        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Instrument file is missing columns: {missing}")

    @staticmethod
    def _build_instrument(row: dict[str, Any]) -> Instrument:
        return Instrument(
            symbol=str(row["tradingsymbol"]).upper(),
            instrument_token=int(row["instrument_token"]),
            exchange=row.get("exchange"),
            name=row.get("name"),
        )
