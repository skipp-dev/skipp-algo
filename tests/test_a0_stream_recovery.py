"""Historical bootstrap and reconnect recovery tests for A0-Fast."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from open_prep.a0_stream_recovery import (
    HistoricalBootstrapBatch,
    RecoveryStatus,
    recover_before_bar,
)
from open_prep.a0_stream_state import (
    A0StreamState,
    StreamApplyStatus,
    StreamBar,
    StreamReference,
)

_ET = ZoneInfo("America/New_York")
_OPEN = datetime(2026, 7, 17, 9, 30, tzinfo=_ET)


def _bar(offset: int, *, volume: int = 100, sequence: int = 1) -> StreamBar:
    event = _OPEN + timedelta(seconds=offset)
    return StreamBar(
        symbol="NVDA",
        close=102.0,
        volume=volume,
        ts_event=event.timestamp(),
        ts_recv=event.timestamp() + 0.1,
        sequence=sequence,
    )


def _state() -> A0StreamState:
    state = A0StreamState(max_gap_seconds=2)
    state.set_reference(StreamReference(
        symbol="NVDA",
        previous_close=100.0,
        average_daily_volume=10_000.0,
        source="databento:daily",
        as_of_session="2026-07-16",
        lookback_sessions=20,
        reference_version="daily-v1",
        corporate_action_version="corp-v1",
    ))
    return state


class _Provider:
    def __init__(self, batch: HistoricalBootstrapBatch) -> None:
        self.batch = batch

    def fetch_before(self, _bar: StreamBar) -> HistoricalBootstrapBatch:
        return self.batch


def test_mid_session_recovery_rebuilds_volume_and_replays_current_bar() -> None:
    state = _state()
    current = _bar(90 * 60, volume=50, sequence=100)
    assert state.apply(current).status is StreamApplyStatus.BOOTSTRAP_REQUIRED
    batch = HistoricalBootstrapBatch(
        symbol="NVDA",
        request_start=_OPEN.timestamp(),
        request_end=current.ts_event,
        coverage_complete=True,
        bars=(
            _bar(0, volume=100, sequence=1),
            _bar(120, volume=200, sequence=2),
            _bar(120, volume=200, sequence=2),
        ),
    )
    outcome = recover_before_bar(state, current, _Provider(batch))
    assert outcome.status is RecoveryStatus.RECOVERED
    assert outcome.historical_bars == 2
    assert outcome.recovered_volume == 300
    assert outcome.apply_result.status is StreamApplyStatus.ACCEPTED
    assert outcome.apply_result.snapshot.cumulative_regular_volume == 350


def test_gap_recovery_overwrites_partial_state() -> None:
    state = _state()
    state.apply(_bar(0, volume=100, sequence=1))
    current = _bar(10, volume=50, sequence=2)
    assert state.apply(current).status is StreamApplyStatus.GAP_DETECTED
    batch = HistoricalBootstrapBatch(
        symbol="NVDA",
        request_start=_OPEN.timestamp(),
        request_end=current.ts_event,
        coverage_complete=True,
        bars=(_bar(0, volume=100, sequence=1), _bar(5, volume=80, sequence=5)),
    )
    outcome = recover_before_bar(state, current, _Provider(batch))
    assert outcome.status is RecoveryStatus.RECOVERED
    assert outcome.apply_result.snapshot.cumulative_regular_volume == 230


def test_incomplete_or_cross_symbol_history_remains_fail_closed() -> None:
    current = _bar(60, sequence=2)
    incomplete = HistoricalBootstrapBatch(
        symbol="NVDA",
        request_start=_OPEN.timestamp() + 1,
        request_end=current.ts_event,
        coverage_complete=True,
        bars=(),
    )
    assert recover_before_bar(_state(), current, _Provider(incomplete)).status is (
        RecoveryStatus.INCOMPLETE_COVERAGE
    )
    wrong = StreamBar(
        symbol="AMD",
        close=102.0,
        volume=100,
        ts_event=_OPEN.timestamp(),
        ts_recv=_OPEN.timestamp() + 0.1,
    )
    invalid = HistoricalBootstrapBatch(
        symbol="NVDA",
        request_start=_OPEN.timestamp(),
        request_end=current.ts_event,
        coverage_complete=True,
        bars=(wrong,),
    )
    assert recover_before_bar(_state(), current, _Provider(invalid)).status is (
        RecoveryStatus.INVALID_HISTORY
    )


def test_provider_failure_is_structured_and_does_not_raise() -> None:
    class _Broken:
        def fetch_before(self, _bar: StreamBar) -> HistoricalBootstrapBatch:
            raise TimeoutError("history unavailable")

    outcome = recover_before_bar(_state(), _bar(60), _Broken())
    assert outcome.status is RecoveryStatus.FETCH_FAILED
    assert "TimeoutError" in outcome.error
