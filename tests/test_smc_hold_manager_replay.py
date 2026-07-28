"""Contracts for the Hold Manager R2.4 repository replay preflight."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import scripts.smc_hold_manager_replay as replay_module
from scripts.smc_hold_manager_replay import (
    CASE_BUILDERS,
    DEFAULT_OUTPUT,
    HARNESS_LIBRARY_PIN,
    build_replay_preflight,
    freeze_library_pin,
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
CURRENT_TRADINGVIEW_PRECONDITIONS_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_preconditions_2026-07-28.json"
)
TRADINGVIEW_REPLAY_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_replay_2026-07-28.json"
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


def test_library_republish_does_not_move_the_preflight_source_hash() -> None:
    """A refresh-only pin bump must not restate the pinned repository evidence.

    ``smc-library-refresh`` rewrites the canonical micro-profiles import three
    times per trading day and cannot regenerate these governance artifacts.
    Since none of the R2.4 evidence depends on the library's contents, the pin
    is frozen before hashing — anything else in the canonical still fails
    closed via ``test_preflight_artifact_is_current_and_source_pinned``.
    """

    baseline = build_replay_preflight()["source"]["sha256"]
    source = replay_module.HOLD_MANAGER_SOURCE.read_text(encoding="utf-8")
    canonical_pin = re.search(
        r"import preuss_steffen/smc_micro_profiles_generated/(\d+)", source
    )
    assert canonical_pin is not None, (
        "Canonical no longer imports the generated micro-profiles library — "
        "the decoupling premise changed, re-read HARNESS_LIBRARY_PIN."
    )
    republished = source.replace(
        f"smc_micro_profiles_generated/{canonical_pin.group(1)}",
        f"smc_micro_profiles_generated/{int(canonical_pin.group(1)) + 99}",
    )
    assert republished != source

    assert (
        hashlib.sha256(freeze_library_pin(republished).encode()).hexdigest()
        == baseline
    )
    assert (
        hashlib.sha256(freeze_library_pin(source).encode()).hexdigest()
        == baseline
    )


def test_freeze_library_pin_touches_only_the_micro_profiles_import() -> None:
    source = replay_module.HOLD_MANAGER_SOURCE.read_text(encoding="utf-8")
    frozen = freeze_library_pin(source)

    assert (
        f"import preuss_steffen/smc_micro_profiles_generated/"
        f"{HARNESS_LIBRARY_PIN} as mp" in frozen
    )
    assert len(frozen.splitlines()) == len(source.splitlines())
    assert [
        line
        for line in frozen.splitlines()
        if "smc_micro_profiles_generated" not in line
    ] == [
        line
        for line in source.splitlines()
        if "smc_micro_profiles_generated" not in line
    ]


def test_historical_tradingview_preconditions_remain_bounded() -> None:
    evidence = json.loads(
        TRADINGVIEW_PRECONDITIONS_PATH.read_text(encoding="utf-8")
    )

    assert evidence["scope"] == (
        "TradingView preconditions only; not R2.4 replay-case evidence"
    )
    assert len(evidence["source"]["repositorySha256"]) == 64
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


def test_current_tradingview_preconditions_match_the_canonical_source() -> None:
    replay = build_replay_preflight()
    evidence = json.loads(
        CURRENT_TRADINGVIEW_PRECONDITIONS_PATH.read_text(encoding="utf-8")
    )

    assert evidence["source"]["repositorySha256"] == replay["source"]["sha256"]
    assert evidence["source"]["transferredSourceSha256"] == (
        replay["source"]["sha256"]
    )
    assert evidence["source"]["savedSourceReadbackStatus"] == (
        "bounded_visible_match_after_reload"
    )
    assert evidence["source"]["savedSourceReadbackSha256"] is None
    assert evidence["tradingView"]["account"] == "preuss_steffen"
    assert evidence["tradingView"]["visibility"] == "private"
    assert evidence["tradingView"]["publicationStatus"] == "not_published"
    assert evidence["tradingView"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["compileDiagnostics"] == []
    assert evidence["tradingView"]["addToChartStatus"] == "passed"
    assert evidence["tradingView"]["coLocationStatus"] == (
        "passed_after_reload"
    )
    assert evidence["tradingView"]["consumerChart"] == "Chart #2"
    assert evidence["tradingView"]["producerLegend"] == "SMC Long-Dip Suite"
    assert evidence["tradingView"]["consumerLegend"] == "SMC Hold Manager"
    assert evidence["tradingView"]["orphanConsumerOnChart1"] is False
    assert evidence["tradingView"]["bindingStatus"] == "passed_after_reload"
    assert evidence["tradingView"]["planSource"] == "Engine BUS v2"
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
    assert evidence["tradingView"]["layoutStateAfterReload"] == {
        "chartCount": 2,
        "timeframeMinutes": 5,
        "replayActive": False,
        "layoutSaved": True,
        "pineEditorClosed": True,
    }
    assert evidence["replay"]["status"] == "complete"
    assert evidence["shadowCutover"] == {
        "status": "not_started",
        "publicationPerformed": False,
        "alertsCreated": False,
        "serverAlertDeliveryStatus": "pending",
    }


def test_tradingview_replay_evidence_is_current_and_reports_success() -> None:
    replay = build_replay_preflight()
    evidence = json.loads(TRADINGVIEW_REPLAY_PATH.read_text(encoding="utf-8"))

    assert evidence["canonicalSource"]["sha256"] == replay["source"]["sha256"]
    assert evidence["fixture"]["sha256"] == (
        "2dadabfdf400e1adb11b597f609d7cd18a09c0642966fff426171886e4888f1d"
    )
    assert evidence["fixture"]["visibility"] == "private"
    assert evidence["fixture"]["publicationStatus"] == "not_published"
    assert evidence["fixture"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["physicalRunsExecuted"] == 23
    assert evidence["tradingView"]["logicalCasesExecuted"] == 20
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True
    assert evidence["results"]["status"] == "passed"
    assert evidence["results"]["passedLogicalCases"] == 20
    assert evidence["results"]["failedLogicalCases"] == 0
    assert evidence["results"]["passedCaseIds"] == [
        case_id for case_id, _name in EXPECTED_CASES
    ]
    assert evidence["results"]["failures"] == []
    assert evidence["results"]["delayedEntryCheck"][
        "observedAtBothCheckpoints"
    ]["phase"] == "IN_TRADE"
    assert evidence["serverAlertDelivery"]["status"] == "pending"


def test_traceability_marks_r2_replay_complete() -> None:
    requirement = _trace_requirement()

    assert requirement["status"] == "complete"
    assert requirement["evidence"] == [
        "scripts/smc_hold_manager_replay.py",
        "scripts/generate_smc_hold_manager_tv_fixture.py",
        "tests/test_smc_hold_manager_replay.py",
        "tests/test_smc_hold_manager_tradingview_fixture.py",
        "tests/fixtures/pine/smc_hold_manager_r2_4_fixture.pine",
        "artifacts/governance/smc_hold_manager_replay_preflight.json",
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_fixture_manifest.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_fixture_compile_2026-07-27.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_fixture_compile_2026-07-28.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_replay_2026-07-28.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_preconditions_2026-07-27.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_preconditions_2026-07-28.json"
        ),
    ]
    assert requirement["openGates"] == []
