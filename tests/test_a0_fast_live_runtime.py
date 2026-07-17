"""Reader-thread integration tests for bounded A0-Fast ingestion."""

from __future__ import annotations

from types import SimpleNamespace

from open_prep.a0_stream_buffer import BoundedBarBuffer
from services.a0_fast_detector.live_runtime import start_live_reader
from services.a0_fast_detector.telemetry import A0FastTelemetry


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
    )
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert client.subscription["schema"] == "ohlcv-1s"
    item = buffer.take(timeout=0)
    assert item.bar.sequence == 2
    assert item.resync_required is True
    snapshot = telemetry.snapshot()
    assert snapshot["records_received"] == 2
    assert snapshot["queue_dropped"] == 1
    assert snapshot["connected"] is False
    assert buffer.snapshot().close_reason == "stream_ended"
