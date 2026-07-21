"""End-to-end processor test from forced resync through persisted shadow A0."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from open_prep.a0_contract import A0ThresholdContext
from open_prep.a0_stream_buffer import BufferedBar
from open_prep.a0_stream_recovery import HistoricalBootstrapBatch
from open_prep.a0_stream_state import A0StreamState, StreamBar, StreamReference
from open_prep.pre_a0_telemetry import PreA0Telemetry
from services.a0_fast_detector.telemetry import A0FastTelemetry
from services.a0_fast_detector.worker import _Processor

_OPEN = datetime(2026, 7, 17, 9, 30, tzinfo=ZoneInfo("America/New_York"))


def _bar(offset: int, *, volume: int, sequence: int) -> StreamBar:
    event = _OPEN + timedelta(seconds=offset)
    return StreamBar(
        symbol="NVDA",
        close=102.0,
        volume=volume,
        ts_event=event.timestamp(),
        ts_recv=event.timestamp() + 0.1,
        sequence=sequence,
    )


class _History:
    def fetch_before(self, current: StreamBar) -> HistoricalBootstrapBatch:
        return HistoricalBootstrapBatch(
            symbol="NVDA",
            request_start=_OPEN.timestamp(),
            request_end=current.ts_event,
            coverage_complete=True,
            bars=(_bar(0, volume=3_000, sequence=1),),
        )


class _Journal:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def record(self, row: dict[str, object]) -> bool:
        self.rows.append(row)
        return True


class _BrokenHistory:
    def fetch_before(self, _current: StreamBar) -> HistoricalBootstrapBatch:
        raise RuntimeError("historical availability lag")


class _PreA0:
    def __init__(self, *, fail: bool = False) -> None:
        self.reset_symbols: list[str] = []
        self.snapshots: list[object] = []
        self.telemetry = PreA0Telemetry()
        self.fail = fail

    def reset(self, symbol: str) -> None:
        self.reset_symbols.append(symbol)

    def process(self, snapshot):
        if self.fail:
            raise ValueError("synthetic PRE-A0 failure")
        self.snapshots.append(snapshot)
        return type("Result", (), {"operator_payload": None})()


def test_forced_resync_recovers_before_persisting_shadow_a0() -> None:
    state = A0StreamState()
    state.set_reference(StreamReference(
        symbol="NVDA",
        previous_close=100.0,
        average_daily_volume=1_000.0,
        source="databento:daily",
        as_of_session="2026-07-16",
        lookback_sessions=20,
        reference_version="daily-v1",
        corporate_action_version="corp-v1",
    ))
    telemetry = A0FastTelemetry()
    telemetry.require_resync("NVDA")
    journal = _Journal()
    pre_a0 = _PreA0()
    processor = _Processor(
        state=state,
        thresholds=A0ThresholdContext(3.0, 1.0, 0.6, 2.0, 1.0, 0.5),
        history=_History(),
        journal=journal,
        telemetry=telemetry,
        pre_a0=pre_a0,
    )

    recovered = processor.process(
        BufferedBar(_bar(30 * 60, volume=100, sequence=2), resync_required=True)
    )
    assert recovered is True
    assert state.state_snapshot("NVDA")["invalidated"] is False
    assert journal.rows[0]["level"] == "A0"
    snapshot = telemetry.snapshot()
    assert snapshot["recovery_counts"] == {"recovered": 1}
    assert snapshot["resync_required"] == 0
    assert snapshot["decisions"] == 1
    assert pre_a0.reset_symbols == ["NVDA", "NVDA"]
    assert len(pre_a0.snapshots) == 1


def test_pre_a0_failure_cannot_suppress_confirmed_a0() -> None:
    state = A0StreamState()
    state.set_reference(StreamReference(
        symbol="NVDA",
        previous_close=100.0,
        average_daily_volume=1_000.0,
        source="databento:daily",
        as_of_session="2026-07-16",
        lookback_sessions=20,
        reference_version="daily-v1",
        corporate_action_version="corp-v1",
    ))
    journal = _Journal()
    pre_a0 = _PreA0(fail=True)
    processor = _Processor(
        state=state,
        thresholds=A0ThresholdContext(3.0, 1.0, 0.6, 2.0, 1.0, 0.5),
        history=_History(),
        journal=journal,
        telemetry=A0FastTelemetry(),
        pre_a0=pre_a0,
    )
    processor.process(
        BufferedBar(_bar(30 * 60, volume=100, sequence=2), resync_required=True)
    )
    assert journal.rows[0]["level"] == "A0"
    assert pre_a0.telemetry.snapshot()["inference_errors"] == 1


def test_failed_historical_recovery_requests_complete_live_replay() -> None:
    state = A0StreamState()
    state.set_reference(StreamReference(
        symbol="NVDA",
        previous_close=100.0,
        average_daily_volume=1_000.0,
        source="databento:daily",
        as_of_session="2026-07-16",
        lookback_sessions=20,
        reference_version="daily-v1",
        corporate_action_version="corp-v1",
    ))
    telemetry = A0FastTelemetry()
    processor = _Processor(
        state=state,
        thresholds=A0ThresholdContext(3.0, 1.0, 0.6, 2.0, 1.0, 0.5),
        history=_BrokenHistory(),
        journal=_Journal(),
        telemetry=telemetry,
    )

    assert processor.process(
        BufferedBar(_bar(30 * 60, volume=100, sequence=2), resync_required=False)
    ) is False
    assert processor.consume_source_replay_request() is True
    assert processor.consume_source_replay_request() is False
    assert telemetry.snapshot()["resync_required"] == 1
