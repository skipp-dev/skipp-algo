"""Contracts for the Hold Manager R2.4 repository replay preflight."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.smc_hold_manager_replay import (
    CASE_BUILDERS,
    DEFAULT_OUTPUT,
    build_replay_preflight,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "pine_extended_migration_traceability.json"
)
TRADINGVIEW_PRECONDITIONS_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_preconditions_2026-07-27.json"
)

EXPECTED_CASES = (
    ("R2.4-01", "arm without entry"),
    ("R2.4-02", "delayed entry after a long wait"),
    ("R2.4-03", "time-stop starts only at entry"),
    ("R2.4-04", "entry and Target 1 on one bar"),
    ("R2.4-05", "entry and stop on one bar"),
    ("R2.4-06", "gap across entry"),
    ("R2.4-07", "gap across stop"),
    ("R2.4-08", "break-even after Target 1"),
    ("R2.4-09", "Chandelier stop never decreases"),
    ("R2.4-10", "Target 2 full exit"),
    ("R2.4-11", "reset during each state"),
    ("R2.4-12", "reload during Armed"),
    ("R2.4-13", "reload during In Trade"),
    ("R2.4-14", "new plan while In Trade"),
    ("R2.4-15", "schema mismatch"),
    ("R2.4-16", "missing BUS input"),
    ("R2.4-17", "stale Micro-Profile context"),
    ("R2.4-18", "event warning without forced false exit"),
    ("R2.4-19", "no duplicate edge alerts"),
    ("R2.4-20", "non-intraday timeframe behavior"),
)


def _trace_requirement() -> dict:
    trace = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    return next(
        requirement
        for phase in trace["phases"]
        for requirement in phase["requirements"]
        if requirement["id"] == "R2-REPLAY"
    )


def test_replay_preflight_executes_the_exact_twenty_case_matrix() -> None:
    payload = build_replay_preflight()

    assert len(CASE_BUILDERS) == 20
    assert payload["caseCount"] == 20
    assert [
        (case["caseId"], case["name"]) for case in payload["cases"]
    ] == list(EXPECTED_CASES)
    assert all(
        case["repositoryPreflightStatus"] == "passed"
        for case in payload["cases"]
    )


def test_every_case_keeps_tradingview_evidence_pending() -> None:
    payload = build_replay_preflight()

    assert payload["gateStatus"] == "partial"
    assert payload["repositoryPreflightStatus"] == "passed"
    assert payload["tradingViewStatus"] == "pending"
    assert all(
        case["tradingViewStatus"] == "pending" for case in payload["cases"]
    )
    assert payload["openGates"]
    assert any(
        "not execution evidence from the Pine runtime" in limitation
        for limitation in payload["limitations"]
    )


def test_preflight_alert_counts_never_duplicate_a_single_event() -> None:
    payload = build_replay_preflight()

    for case in payload["cases"]:
        assert all(
            count <= case["runCount"]
            for count in case["alertCounts"].values()
        ), case["caseId"]


def test_preflight_artifact_is_current_and_source_pinned() -> None:
    expected = build_replay_preflight()
    actual = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert actual == expected
    assert actual["source"]["path"] == "SMC_Hold_Manager.pine"
    assert len(actual["source"]["sha256"]) == 64


def test_tradingview_preconditions_are_bounded_and_source_pinned() -> None:
    replay = build_replay_preflight()
    evidence = json.loads(
        TRADINGVIEW_PRECONDITIONS_PATH.read_text(encoding="utf-8")
    )

    assert evidence["scope"] == (
        "TradingView preconditions only; not R2.4 replay-case evidence"
    )
    assert (
        evidence["source"]["repositorySha256"]
        == replay["source"]["sha256"]
    )
    assert evidence["source"]["savedSourceReadbackStatus"] == "pending"
    assert evidence["tradingView"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["compileDiagnostics"] == []
    assert evidence["tradingView"]["addToChartStatus"] == "passed"
    assert evidence["tradingView"]["bindingStatus"] == "passed_after_reload"
    assert evidence["tradingView"]["bindings"] == {
        f"BUS {name}": f"SMC Long-Dip Suite: BUS {name}"
        for name in (
            "SchemaVersion",
            "ZoneActive",
            "Armed",
            "Confirmed",
            "Ready",
            "Trigger",
            "Invalidation",
            "QualityScore",
            "SourceKind",
            "StateCode",
            "StopLevel",
            "Target1",
            "Target2",
        )
    }
    assert evidence["replay"]["status"] == "pending"
    assert evidence["replay"]["completedCaseIds"] == []
    assert evidence["replay"]["pendingCaseIds"] == [
        case_id for case_id, _name in EXPECTED_CASES
    ]


def test_traceability_marks_r2_replay_partial_not_complete() -> None:
    requirement = _trace_requirement()

    assert requirement["status"] == "partial"
    assert requirement["evidence"] == [
        "scripts/smc_hold_manager_replay.py",
        "tests/test_smc_hold_manager_replay.py",
        "artifacts/governance/smc_hold_manager_replay_preflight.json",
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_preconditions_2026-07-27.json"
        ),
    ]
    assert requirement["openGates"] == [
        (
            "Execute the pinned twenty-case matrix in TradingView and retain "
            "compile, diagnostic, reload, Bar Replay, and alert-count evidence."
        )
    ]
