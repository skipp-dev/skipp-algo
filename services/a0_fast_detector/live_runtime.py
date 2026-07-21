"""Databento reader thread feeding the bounded A0-Fast bar buffer."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from open_prep.a0_stream import DatabentoOhlcv1sAdapter
from open_prep.a0_stream_buffer import BoundedBarBuffer

from .telemetry import A0FastTelemetry

logger = logging.getLogger(__name__)


def start_live_reader(
    client_or_factory: Any,
    *,
    symbols: list[str],
    buffer: BoundedBarBuffer,
    telemetry: A0FastTelemetry,
    replay_start: datetime,
) -> threading.Thread:
    """Create, subscribe, and drain the SDK client on one daemon thread.

    Databento's live client owns an event loop with thread affinity, so a
    factory must be constructed inside this reader thread in production.
    Pre-built iterator fakes remain supported for focused tests.
    """

    def target() -> None:
        reason = "stream_ended"
        try:
            client = client_or_factory() if callable(client_or_factory) else client_or_factory
            _read(
                client,
                symbols=symbols,
                buffer=buffer,
                telemetry=telemetry,
                replay_start=replay_start,
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning("A0-Fast live reader stopped: %s", reason)
        finally:
            telemetry.set_connected(False)
            buffer.close(reason)

    thread = threading.Thread(target=target, name="a0-fast-live-reader", daemon=True)
    thread.start()
    return thread


def _read(
    client: Any,
    *,
    symbols: list[str],
    buffer: BoundedBarBuffer,
    telemetry: A0FastTelemetry,
    replay_start: datetime,
) -> None:
    client.subscribe(
        dataset="EQUS.MINI",
        schema="ohlcv-1s",
        symbols=symbols,
        stype_in="raw_symbol",
        start=replay_start,
    )
    telemetry.set_connected(True)
    adapter = DatabentoOhlcv1sAdapter()
    symbol_map: dict[int, str] = {}
    replay_active = True
    for record in client:
        record_type = type(record).__name__
        if record_type == "SymbolMappingMsg":
            instrument_id = getattr(record, "instrument_id", None)
            raw_symbol = getattr(record, "stype_out_symbol", None)
            if instrument_id is not None and raw_symbol:
                symbol_map[int(instrument_id)] = str(raw_symbol).strip().upper()
            continue
        if record_type == "SystemMsg":
            if _system_code(record) == "replay_completed":
                replay_active = False
            continue
        if "OHLCV" not in record_type.upper() and "BAR" not in record_type.upper():
            continue
        telemetry.record_received()
        symbol = _symbol_from_record(record, symbol_map)
        if symbol is None:
            telemetry.record_rejected("unmapped_symbol")
            continue
        try:
            bar = adapter.normalize(record, symbol=symbol)
        except (TypeError, ValueError, OverflowError):
            telemetry.record_rejected("invalid_record")
            logger.debug("A0-Fast rejected malformed stream record", exc_info=True)
            continue
        # Intraday replay arrives much faster than wall clock.  Apply bounded
        # backpressure until Databento announces replay completion so complete
        # source history is preserved.  Once live, prefer latency and retain
        # the existing fail-closed drop/resync contract on overload.
        offer = buffer.put(bar) if replay_active else buffer.offer(bar)
        if offer.dropped is not None:
            telemetry.record_queue_drop()
        telemetry.set_buffer(buffer.snapshot())


def _system_code(record: Any) -> str:
    code = getattr(record, "code", "")
    value = getattr(code, "value", code)
    return str(value).strip().lower()


def _symbol_from_record(record: Any, symbol_map: dict[int, str]) -> str | None:
    instrument_id = getattr(record, "instrument_id", None)
    if instrument_id is None:
        header = getattr(record, "hd", None)
        instrument_id = getattr(header, "instrument_id", None)
    return symbol_map.get(instrument_id) if instrument_id is not None else None
