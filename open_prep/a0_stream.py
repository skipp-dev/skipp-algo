"""Databento OHLCV-1s normalization for the isolated A0-Fast shadow path."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .a0_stream_state import StreamBar

_ATTR_READERS = {
    "close": lambda record: getattr(record, "close", None),
    "volume": lambda record: getattr(record, "volume", None),
    "ts_event": lambda record: getattr(
        record, "ts_event", getattr(getattr(record, "hd", None), "ts_event", None)
    ),
    "ts_recv": lambda record: getattr(
        record, "ts_recv", getattr(getattr(record, "hd", None), "ts_recv", None)
    ),
    "sequence": lambda record: getattr(
        record, "sequence", getattr(getattr(record, "hd", None), "sequence", None)
    ),
}


def _field(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    reader = _ATTR_READERS.get(name)
    if reader is None:
        return default
    value = reader(record)
    return default if value is None else value


def _epoch_seconds(value: Any) -> float:
    epoch = float(value)
    if epoch >= 100_000_000_000_000_000:
        return epoch / 1_000_000_000.0
    if epoch >= 1_000_000_000_000:
        return epoch / 1000.0
    return epoch


@dataclass(frozen=True, slots=True)
class DatabentoOhlcv1sAdapter:
    """Normalize SDK records; deliberately contains no A0 level logic."""

    price_scale: float = 1e-9

    def normalize(self, record: Any, *, symbol: str, received_at: float | None = None) -> StreamBar:
        raw_close = _field(record, "close")
        raw_volume = _field(record, "volume")
        raw_event = _field(record, "ts_event")
        if raw_close is None or raw_volume is None or raw_event is None:
            raise ValueError("OHLCV-1s record is missing close, volume, or ts_event")
        close = float(raw_close) * self.price_scale
        volume = int(raw_volume)
        ts_event = _epoch_seconds(raw_event)
        raw_recv = _field(record, "ts_recv", received_at if received_at is not None else raw_event)
        ts_recv = _epoch_seconds(raw_recv)
        raw_sequence = _field(record, "sequence")
        sequence = int(raw_sequence) if raw_sequence is not None else None
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol or close <= 0 or volume < 0:
            raise ValueError("OHLCV-1s record contains invalid symbol, close, or volume")
        return StreamBar(
            symbol=normalized_symbol,
            close=close,
            volume=volume,
            ts_event=ts_event,
            ts_recv=ts_recv,
            sequence=sequence,
        )
