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


class SystemMsg:
    code = "replay_completed"


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
    client = _Client(
        [SymbolMappingMsg(), SystemMsg(), OhlcvMsg(1), OhlcvMsg(2)]
    )
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


def test_reader_applies_backpressure_during_replay_without_dropping() -> None:
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

    first = buffer.take(timeout=1)
    second = buffer.take(timeout=1)
    thread.join(timeout=2)

    assert first is not None and first.bar.sequence == 1
    assert second is not None and second.bar.sequence == 2
    assert not thread.is_alive()
    assert telemetry.snapshot()["queue_dropped"] == 0


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
    # Seit dem Seeding (SEEDED_REJECTION_REASONS in
    # services/a0_fast_detector/telemetry.py) existiert die Familie ab Start
    # mit 0 je Grund, damit increase() den ersten Burst nicht als Baseline
    # frisst. "Nichts abgelehnt" ist deshalb die SUMME 0, nicht das leere
    # Dict -- die Absicht des Tests bleibt, nur seine Form aendert sich.
    assert sum(telemetry.snapshot()["record_rejections"].values()) == 0


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


class _BlockedClient:
    """Iterator that blocks exactly like a paused DBN transport: no records,
    no exception — until stop() releases it (then the iteration ends)."""

    def __init__(self) -> None:
        self.subscription: dict[str, object] = {}
        self.stopped = threading.Event()

    def subscribe(self, **kwargs: object) -> None:
        self.subscription = kwargs

    def stop(self) -> None:
        self.stopped.set()

    def __iter__(self):
        return self

    def __next__(self):
        # Block until the stall-breaker calls stop(); a real paused
        # transport would block forever.
        if self.stopped.wait(timeout=30):
            raise StopIteration
        raise AssertionError("watchdog never broke the blocked iterator")


def test_watchdog_breaks_a_blocked_iterator_and_reports_reader_stalled() -> None:
    """2026-08-18 (Grenzgaenger D6): a subscribe-time burst can pause the DBN
    transport and block ``for record in client:`` forever WITHOUT an
    exception — the worker then spins on an open buffer for good (13h on
    2026-08-17 was the consumer-side variant). The watchdog must break the
    iterator via client.stop() and close the buffer with reason
    ``reader_stalled`` so the worker's reconnect path takes over."""
    client = _BlockedClient()
    buffer = BoundedBarBuffer(capacity=2)
    telemetry = A0FastTelemetry()
    thread = start_live_reader(
        client,
        symbols=["NVDA"],
        buffer=buffer,
        telemetry=telemetry,
        replay_start=_REPLAY_START,
        stall_break_after_secs=0.2,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert client.stopped.is_set()
    assert buffer.snapshot().closed
    assert buffer.snapshot().close_reason == "reader_stalled"
    assert telemetry.snapshot()["connected"] is False


def test_records_keep_resetting_the_stall_clock() -> None:
    """A slow-but-alive stream (heartbeats/mappings count as liveness) must
    never be broken: the reader ends normally with stream_ended."""
    import time as _time

    class _SlowClient(_Client):
        def __iter__(self):
            def gen():
                for record in self.records:
                    _time.sleep(0.1)
                    yield record
            return gen()

    client = _SlowClient([SymbolMappingMsg(), SystemMsg(), OhlcvMsg(1)])
    buffer = BoundedBarBuffer(capacity=2)
    telemetry = A0FastTelemetry()
    thread = start_live_reader(
        client,
        symbols=["NVDA"],
        buffer=buffer,
        telemetry=telemetry,
        replay_start=_REPLAY_START,
        stall_break_after_secs=0.25,
    )
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert buffer.snapshot().close_reason == "stream_ended"
