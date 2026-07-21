"""Reader-thread integration tests for bounded A0-Fast ingestion."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from types import SimpleNamespace

from databento_dbn import OHLCVMsg, RType

from open_prep.a0_stream_buffer import BoundedBarBuffer
from services.a0_fast_detector.live_runtime import start_live_reader
from services.a0_fast_detector.telemetry import A0FastTelemetry

_REPLAY_START = datetime(2026, 7, 21, 13, 30, tzinfo=UTC)


class SymbolMappingMsg:
    instrument_id = 1
    stype_out_symbol = "NVDA"


class OhlcvMsg:
    def __init__(self, sequence: int) -> None:
        self.close = 102_000_000_000
        self.volume = 100
        self.ts_event = 1_752_758_200_000_000_000 + sequence * 1_000_000_000
        self.ts_recv = self.ts_event + 100_000_000
        self.sequence = sequence
        self.hd = SimpleNamespace(instrument_id=1)


class UnmappedOhlcvMsg(OhlcvMsg):
    def __init__(self) -> None:
        super().__init__(1)
        self.hd = SimpleNamespace(instrument_id=2)


class InvalidOhlcvMsg(OhlcvMsg):
    def __init__(self) -> None:
        super().__init__(2)
        self.close = None


class _Client:
    def __init__(self, records: list[object]) -> None:
        self.records = records
        self.subscription: dict[str, object] = {}

    def subscribe(self, **kwargs: object) -> None:
        self.subscription = kwargs

    def __iter__(self):
        return iter(self.records)


def test_reader_normalizes_into_bounded_buffer_and_exposes_overflow() -> None:
    client = _Client([SymbolMappingMsg(), OhlcvMsg(1), OhlcvMsg(2)])
    buffer = BoundedBarBuffer(capacity=1)
    telemetry = A0FastTelemetry()
    thread = start_live_reader(
        client,
        symbols=["NVDA"],
        buffer=buffer,
        telemetry=telemetry,
        replay_start=_REPLAY_START,
    )
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert client.subscription["schema"] == "ohlcv-1s"
    assert client.subscription["start"] == _REPLAY_START
    item = buffer.take(timeout=0)
    assert item.bar.sequence == 2
    assert item.resync_required is True
    snapshot = telemetry.snapshot()
    assert snapshot["records_received"] == 2
    assert snapshot["queue_dropped"] == 1
    assert snapshot["connected"] is False
    assert buffer.snapshot().close_reason == "stream_ended"


def test_reader_constructs_live_client_inside_reader_thread() -> None:
    created_on: list[int] = []
    client = _Client([SymbolMappingMsg(), OhlcvMsg(1)])

    def factory() -> _Client:
        created_on.append(threading.get_ident())
        return client

    buffer = BoundedBarBuffer(capacity=2)
    thread = start_live_reader(
        factory,
        symbols=["NVDA"],
        buffer=buffer,
        telemetry=A0FastTelemetry(),
        replay_start=_REPLAY_START,
    )
    thread.join(timeout=2)

    assert created_on == [thread.ident]
    assert created_on[0] != threading.get_ident()
    assert buffer.take(timeout=0) is not None


def test_reader_accepts_real_databento_ohlcv_without_receive_timestamp() -> None:
    event_ns = 1_752_758_200_000_000_000
    record = OHLCVMsg(
        RType.OHLCV_1S,
        1,
        1,
        event_ns,
        102_000_000_000,
        102_000_000_000,
        102_000_000_000,
        102_000_000_000,
        100,
    )
    client = _Client([SymbolMappingMsg(), record])
    buffer = BoundedBarBuffer(capacity=2)
    telemetry = A0FastTelemetry()

    thread = start_live_reader(
        client,
        symbols=["NVDA"],
        buffer=buffer,
        telemetry=telemetry,
        replay_start=_REPLAY_START,
    )
    thread.join(timeout=2)

    item = buffer.take(timeout=0)
    assert item is not None
    assert item.bar.ts_event == event_ns / 1_000_000_000
    assert item.bar.ts_recv == item.bar.ts_event
    assert telemetry.snapshot()["record_rejections"] == {}


def test_reader_counts_unmapped_and_invalid_records() -> None:
    client = _Client([SymbolMappingMsg(), UnmappedOhlcvMsg(), InvalidOhlcvMsg()])
    buffer = BoundedBarBuffer(capacity=2)
    telemetry = A0FastTelemetry()

    thread = start_live_reader(
        client,
        symbols=["NVDA"],
        buffer=buffer,
        telemetry=telemetry,
        replay_start=_REPLAY_START,
    )
    thread.join(timeout=2)

    snapshot = telemetry.snapshot()
    assert snapshot["records_received"] == 2
    assert snapshot["record_rejections"] == {
        "invalid_record": 1,
        "unmapped_symbol": 1,
    }
