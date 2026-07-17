"""End-to-end processor test from forced resync through persisted shadow A0."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from open_prep.a0_contract import A0ThresholdContext
from open_prep.a0_stream_buffer import BufferedBar
from open_prep.a0_stream_recovery import HistoricalBootstrapBatch
from open_prep.a0_stream_state import A0StreamState, StreamBar, StreamReference
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
    processor = _Processor(
        state=state,
        thresholds=A0ThresholdContext(3.0, 1.0, 0.6, 2.0, 1.0, 0.5),
        history=_History(),
        journal=journal,
        telemetry=telemetry,
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
