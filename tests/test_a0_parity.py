"""Parity class and lead-time tests for A0-Fast shadow matching."""

from __future__ import annotations

from dataclasses import replace

from open_prep.a0_parity import (
    ParityMatchStatus,
    ShadowDecision,
    build_parity_report,
    match_shadow_decisions,
)


def _decision(
    decision_id: str,
    symbol: str,
    direction: str,
    decision_at: float,
    source: str,
) -> ShadowDecision:
    return ShadowDecision(
        decision_id=decision_id,
        symbol=symbol,
        direction=direction,
        level="A0",
        decision_at=decision_at,
        source=source,
        reason_codes=("core_a0_thresholds",),
    )


def test_matcher_classifies_lead_direction_and_mismatch() -> None:
    fast = [
        _decision("fast-1", "NVDA", "LONG", 100.0, "databento"),
        _decision("fast-2", "AMD", "SHORT", 200.0, "databento"),
        _decision("fast-3", "TSLA", "LONG", 300.0, "databento"),
    ]
    fmp = [
        _decision("fmp-1", "NVDA", "LONG", 108.0, "fmp"),
        _decision("fmp-2", "AMD", "SHORT", 195.0, "fmp"),
        _decision("fmp-3", "TSLA", "SHORT", 302.0, "fmp"),
    ]
    matches = match_shadow_decisions(fast, fmp, matching_window_seconds=10)
    assert [match.status for match in matches] == [
        ParityMatchStatus.SAME_DECISION_FAST_FIRST,
        ParityMatchStatus.SAME_DECISION_FMP_FIRST,
        ParityMatchStatus.RULE_STATE_MISMATCH,
    ]
    assert matches[0].lead_seconds == 8.0
    assert matches[1].lead_seconds == -5.0


def test_matcher_explains_fast_only_and_fmp_only_data_gap() -> None:
    fast = [_decision("fast", "NVDA", "LONG", 100.0, "databento")]
    fmp = [_decision("fmp", "AMD", "LONG", 100.0, "fmp")]
    matches = match_shadow_decisions(
        fast,
        fmp,
        matching_window_seconds=5,
        stream_health_by_symbol={"AMD": "gap_detected"},
    )
    assert matches[0].status is ParityMatchStatus.FAST_ONLY_SOURCE_SEMANTICS
    assert matches[1].status is ParityMatchStatus.FMP_ONLY_MISSING_STREAM_DATA


def test_report_keeps_cause_classes_and_fast_lead_median() -> None:
    matches = match_shadow_decisions(
        [
            _decision("fast-1", "NVDA", "LONG", 100.0, "databento"),
            _decision("fast-2", "AMD", "LONG", 200.0, "databento"),
        ],
        [
            _decision("fmp-1", "NVDA", "LONG", 104.0, "fmp"),
            _decision("fmp-2", "AMD", "LONG", 212.0, "fmp"),
        ],
        matching_window_seconds=20,
    )
    report = build_parity_report(matches)
    assert report["matched_same_direction"] == 2
    assert report["median_fast_lead_seconds"] == 8.0
    assert report["status_counts"] == {"same_decision_fast_first": 2}
    assert report["matches"][0]["fast_snapshot"]["decision_id"] == "fast-1"
    assert report["matches"][0]["fmp_snapshot"]["decision_id"] == "fmp-1"


def test_core_only_fast_requires_fmp_core_a0_for_same_decision() -> None:
    fast = replace(
        _decision("fast", "NVDA", "LONG", 100.0, "databento"),
        decision_scope="core_only",
        core_level="A0",
    )
    fmp = replace(
        _decision("fmp", "NVDA", "LONG", 101.0, "fmp"),
        core_level="A1",
    )
    matches = match_shadow_decisions([fast], [fmp], matching_window_seconds=5)
    assert matches[0].status is ParityMatchStatus.RULE_STATE_MISMATCH
