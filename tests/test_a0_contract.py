"""Contract tests for provider-neutral, replayable A0 decisions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from open_prep.a0_contract import (
    A0ReasonCode,
    A0ThresholdContext,
    amend_decision_details,
    build_market_snapshot,
    decide_core_level,
)

NOW = datetime(2026, 7, 17, 14, 30, tzinfo=UTC).timestamp()
THRESHOLDS = A0ThresholdContext(
    a0_volume=3.0,
    a1_volume=1.0,
    a2_volume=0.6,
    a0_price=2.0,
    a1_price=1.0,
    a2_price=0.5,
)


def _snapshot(*, pace: float, change: float, ts_event: object = NOW - 2):
    return build_market_snapshot(
        symbol="nvda",
        price=102.0,
        prev_close=100.0,
        change_pct=change,
        raw_daily_volume_ratio=0.75,
        expected_volume_fraction=0.25,
        normalized_volume_pace=pace,
        source="FMP",
        raw_ts_event=ts_event,
        observed_at=NOW,
    )


@pytest.mark.parametrize(
    ("pace", "change", "level", "reason"),
    [
        (3.0, 2.0, "A0", A0ReasonCode.CORE_A0_THRESHOLDS),
        (1.0, 1.0, "A1", A0ReasonCode.CORE_A1_THRESHOLDS),
        (0.1, 2.4, "A1", A0ReasonCode.CORE_A1_LARGE_MOVE),
        (0.6, 0.5, "A2", A0ReasonCode.CORE_A2_THRESHOLDS),
        (0.1, 1.5, "A2", A0ReasonCode.CORE_A2_LARGE_MOVE),
        (0.59, 0.49, None, None),
    ],
)
def test_core_threshold_ladder(
    pace: float,
    change: float,
    level: str | None,
    reason: A0ReasonCode | None,
) -> None:
    decision = decide_core_level(_snapshot(pace=pace, change=change), THRESHOLDS)
    assert decision.core_level == level
    assert decision.final_level == level
    assert decision.reason_codes == (() if reason is None else (str(reason),))


def test_timestamp_contract_accepts_milliseconds_and_measures_age() -> None:
    snapshot = _snapshot(pace=3.0, change=2.0, ts_event=(NOW - 2) * 1000)
    assert snapshot.ts_event == NOW - 2
    assert snapshot.data_age_ms == 2000.0
    assert snapshot.data_age_unknown is False
    assert snapshot.source == "fmp"
    assert snapshot.session_date == "2026-07-17"


@pytest.mark.parametrize("bad_timestamp", [None, "bad", 42, NOW + 61])
def test_implausible_timestamp_is_explicitly_unknown(bad_timestamp: object) -> None:
    snapshot = _snapshot(pace=3.0, change=2.0, ts_event=bad_timestamp)
    assert snapshot.ts_event is None
    assert snapshot.data_age_ms is None
    assert snapshot.data_age_unknown is True


def test_retry_of_same_semantic_decision_has_stable_id() -> None:
    snapshot = _snapshot(pace=3.0, change=2.0)
    first = decide_core_level(snapshot, THRESHOLDS, decision_at=NOW)
    retried = decide_core_level(snapshot, THRESHOLDS, decision_at=NOW + 10)
    assert first.decision_id == retried.decision_id


def test_final_modifier_is_replayable_and_explained() -> None:
    core = decide_core_level(_snapshot(pace=3.0, change=2.0), THRESHOLDS)
    final = core.with_final_level(
        "A1",
        [*core.reason_codes, A0ReasonCode.COOLDOWN_DOWNGRADE],
    )
    assert final.core_level == "A0"
    assert final.final_level == "A1"
    assert final.reason_codes[-1] == A0ReasonCode.COOLDOWN_DOWNGRADE
    assert final.decision_id != core.decision_id


def test_stateful_amendment_updates_final_level_and_id_deterministically() -> None:
    core = decide_core_level(_snapshot(pace=1.0, change=1.0), THRESHOLDS)
    first = core.to_details()
    retried = core.to_details()
    amend_decision_details(
        first,
        final_level="A0",
        reason_code=A0ReasonCode.NEWS_CATALYST_UPGRADE,
    )
    amend_decision_details(
        retried,
        final_level="A0",
        reason_code=A0ReasonCode.NEWS_CATALYST_UPGRADE,
    )
    assert first["final_level"] == "A0"
    assert first["reason_codes"][-1] == A0ReasonCode.NEWS_CATALYST_UPGRADE
    assert first["decision_id"] == retried["decision_id"]
