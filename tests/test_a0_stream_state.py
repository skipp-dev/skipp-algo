"""Deterministic replay and fail-closed tests for the A0-Fast stream state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from open_prep.a0_contract import A0ThresholdContext, decide_core_level
from open_prep.a0_stream import DatabentoOhlcv1sAdapter
from open_prep.a0_stream_state import (
    A0StreamState,
    GapState,
    StreamApplyStatus,
    StreamBar,
    StreamReference,
    expected_regular_volume_fraction,
)

_ET = ZoneInfo("America/New_York")
_OPEN = datetime(2026, 7, 17, 9, 30, tzinfo=_ET)


def _reference(*, source: str = "databento:eq us.mini") -> StreamReference:
    return StreamReference(
        symbol="NVDA",
        previous_close=100.0,
        average_daily_volume=10_000.0,
        source=source,
        as_of_session="2026-07-16",
        lookback_sessions=20,
        reference_version="db-daily-v1",
        corporate_action_version="db-corp-v1",
    )


def _bar(offset_s: int, *, volume: int = 100, sequence: int = 1) -> StreamBar:
    event = _OPEN + timedelta(seconds=offset_s)
    return StreamBar(
        symbol="nvda",
        close=102.0,
        volume=volume,
        ts_event=event.timestamp(),
        ts_recv=event.timestamp() + 0.1,
        sequence=sequence,
    )


def test_databento_adapter_preserves_event_and_receive_time() -> None:
    event_ns = int(_OPEN.timestamp() * 1_000_000_000)
    record = SimpleNamespace(
        close=102_500_000_000,
        volume=321,
        ts_event=event_ns,
        ts_recv=event_ns + 100_000_000,
        sequence=7,
    )
    bar = DatabentoOhlcv1sAdapter().normalize(record, symbol=" nvda ")
    assert bar.symbol == "NVDA"
    assert bar.close == 102.5
    assert bar.volume == 321
    assert bar.ts_event == _OPEN.timestamp()
    assert bar.ts_recv == pytest.approx(_OPEN.timestamp() + 0.1)
    assert bar.sequence == 7


def test_duplicate_and_out_of_order_bars_do_not_double_count() -> None:
    state = A0StreamState()
    state.set_reference(_reference())
    first = state.apply(_bar(0, volume=100, sequence=1))
    duplicate = state.apply(_bar(0, volume=100, sequence=1))
    state.apply(_bar(1, volume=50, sequence=2))
    out_of_order = state.apply(_bar(0, volume=500, sequence=99))
    assert first.status is StreamApplyStatus.ACCEPTED
    assert duplicate.status is StreamApplyStatus.DUPLICATE
    assert out_of_order.status is StreamApplyStatus.OUT_OF_ORDER
    assert state.state_snapshot("NVDA")["cumulative_volume"] == 150


def test_mid_session_start_requires_proven_bootstrap() -> None:
    state = A0StreamState()
    state.set_reference(_reference())
    midday = _bar(90 * 60, sequence=10)
    result = state.apply(midday)
    assert result.status is StreamApplyStatus.BOOTSTRAP_REQUIRED
    assert result.snapshot is None

    state.bootstrap(
        symbol="NVDA",
        session_date="2026-07-17",
        cumulative_volume=2_000,
        last_ts_event=midday.ts_event,
        last_sequence=midday.sequence,
    )
    recovered = state.apply(_bar(90 * 60 + 1, volume=50, sequence=11))
    assert recovered.status is StreamApplyStatus.ACCEPTED
    assert recovered.snapshot.cumulative_regular_volume == 2_050


def test_gap_detection_stays_fail_closed_until_bootstrap() -> None:
    state = A0StreamState(max_gap_seconds=2)
    state.set_reference(_reference())
    assert state.apply(_bar(0, sequence=1)).snapshot is not None
    gap = state.apply(_bar(5, sequence=2))
    assert gap.status is StreamApplyStatus.GAP_DETECTED
    assert gap.gap_state is GapState.GAP_DETECTED
    assert gap.snapshot is None
    still_closed = state.apply(_bar(6, sequence=3))
    assert still_closed.snapshot is None


def test_reference_must_be_present_and_databento_source_pure() -> None:
    missing = A0StreamState().apply(_bar(0))
    assert missing.status is StreamApplyStatus.REFERENCE_MISSING
    state = A0StreamState()
    state.set_reference(_reference(source="fmp"))
    invalid = state.apply(_bar(0))
    assert invalid.status is StreamApplyStatus.REFERENCE_INVALID
    assert invalid.snapshot is None


def test_half_day_volume_curve_reaches_one_at_early_close() -> None:
    almost_close = datetime(2026, 11, 27, 12, 59, 59, tzinfo=_ET).timestamp()
    assert expected_regular_volume_fraction(almost_close) > 0.99


def test_half_day_volume_curve_knee_scales_to_session_length() -> None:
    # 2026-11-27 is an early-close (13:00 ET) session. Thirty clock-minutes in
    # must land exactly on the first-knee 25% mark; the pre-fix code scaled the
    # knees to a full 390-min day and overshot (~0.31) on half days.
    thirty_minutes_in = datetime(2026, 11, 27, 10, 0, 0, tzinfo=_ET).timestamp()
    assert abs(expected_regular_volume_fraction(thirty_minutes_in) - 0.25) < 1e-9


def test_replay_is_deterministic_and_uses_common_decider() -> None:
    rows = json.loads(
        (Path(__file__).parent / "fixtures" / "a0_stream_replay.json").read_text(
            encoding="utf-8"
        )
    )
    adapter = DatabentoOhlcv1sAdapter()
    decisions = []
    for _run in range(2):
        state = A0StreamState()
        state.set_reference(_reference())
        final = None
        for row in rows:
            event_ns = int(
                (_OPEN + timedelta(seconds=row["offset_s"])).timestamp()
                * 1_000_000_000
            )
            bar = adapter.normalize(
                {
                    "close": row["close_nano"],
                    "volume": row["volume"],
                    "ts_event": event_ns,
                    "ts_recv": event_ns + 100_000_000,
                    "sequence": row["sequence"],
                },
                symbol="NVDA",
            )
            final = state.apply(bar)
        assert final is not None and final.snapshot is not None
        decision = decide_core_level(
            final.snapshot.market,
            A0ThresholdContext(3.0, 1.0, 0.6, 2.0, 1.0, 0.5),
        )
        decisions.append(decision)
    assert decisions[0].decision_id == decisions[1].decision_id
    assert decisions[0].final_level == "A0"
    assert decisions[0].snapshot.source.startswith("databento")
