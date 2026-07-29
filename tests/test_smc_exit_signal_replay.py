"""Contracts for the R1 Exit Signal repository and TradingView replay preflight."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_smc_exit_signal_tv_fixture import (
    FIXTURE,
    MANIFEST,
    build_fixture,
    build_manifest,
)
from scripts.smc_exit_signal_replay import (
    ALERT_ANY,
    ALERT_STOP,
    ALERT_TP1,
    ALERT_TP2,
    CASES,
    DEFAULT_OUTPUT,
    build_replay_preflight,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "artifacts" / "governance" / "pine_extended_migration_traceability.json"
TRADINGVIEW_REPLAY = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_exit_signal_tradingview_replay_2026-07-29.json"
)
LIVE_ROLLOUT_EVIDENCE = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_r1_live_rollout_evidence_2026-07-29.json"
)
ROLLOUT = ROOT / "automation" / "tradingview" / "config" / "consumer-rollout.json"


def _trace_requirement(requirement_id: str) -> dict:
    payload = json.loads(TRACE.read_text(encoding="utf-8"))
    return next(
        requirement
        for phase in payload["phases"]
        for requirement in phase["requirements"]
        if requirement["id"] == requirement_id
    )


def test_repository_preflight_executes_the_registered_matrix() -> None:
    payload = build_replay_preflight()

    assert payload["caseCount"] == len(CASES) == 12
    assert payload["repositoryPreflightStatus"] == "passed"
    assert payload["gateStatus"] == "partial"
    assert payload["tradingViewStatus"] == "pending"
    assert all(case["repositoryPreflightStatus"] == "passed" for case in payload["cases"])


def test_same_bar_precedence_and_one_shot_edges_are_discriminating() -> None:
    cases = {case["caseId"]: case for case in build_replay_preflight()["cases"]}

    assert cases["R1-03"]["alertCounts"] == {
        "EXIT_ANY": 1,
        "EXIT_ENTER": 1,
        "EXIT_STOP": 1,
    }
    assert cases["R1-05"]["alertCounts"][ALERT_TP1] == 1
    assert cases["R1-05"]["alertCounts"][ALERT_TP2] == 1
    assert cases["R1-05"]["alertCounts"][ALERT_ANY] == 1
    assert ALERT_TP1 not in cases["R1-06"]["alertCounts"]
    assert ALERT_TP2 not in cases["R1-06"]["alertCounts"]
    assert cases["R1-06"]["alertCounts"][ALERT_STOP] == 1
    assert cases["R1-07"]["alertCounts"][ALERT_TP1] == 1


def test_checked_in_repository_preflight_is_current() -> None:
    assert json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8")) == build_replay_preflight()


def test_generated_fixture_and_manifest_are_current() -> None:
    fixture = build_fixture()

    assert FIXTURE.read_text(encoding="utf-8") == fixture
    assert json.loads(MANIFEST.read_text(encoding="utf-8")) == build_manifest(fixture)
    assert "SMC Exit Signal R1 Fixture TEST ONLY" in fixture
    assert 'runtime.error("R1 fixture mismatch: "' in fixture
    assert "Canonical source SHA-256:" in fixture
    assert "input.source(" not in fixture


def test_fixture_is_not_a_managed_or_publishable_surface() -> None:
    rollout = ROLLOUT.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert FIXTURE.name not in rollout
    assert manifest["surfaceClass"] == "test_only_not_managed_not_publishable"
    assert manifest["gateStatus"] == "partial"
    assert all(case["tradingViewStatus"] == "pending" for case in manifest["cases"])


def test_tradingview_replay_evidence_is_complete_without_claiming_rollout() -> None:
    evidence = json.loads(TRADINGVIEW_REPLAY.read_text(encoding="utf-8"))

    assert evidence["fixture"]["sha256"] == build_manifest(build_fixture())["fixture"][
        "sha256"
    ]
    assert evidence["fixture"]["sourceReadbackSha256"] == evidence["fixture"]["sha256"]
    assert evidence["fixture"]["compileStatus"] == "passed"
    assert evidence["results"]["status"] == "passed"
    assert evidence["results"]["passedLogicalCases"] == 11
    assert evidence["results"]["failedLogicalCases"] == 0
    assert {case["caseId"] for case in evidence["results"]["cases"]} == {
        f"R1-{case_number:02d}" for case_number in range(1, 12)
    }
    assert all(case["status"] == "passed" for case in evidence["results"]["cases"])
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True
    assert evidence["productLayoutExclusivity"]["status"] == "pending"


def test_traceability_records_completed_tv_replay_and_live_rollout() -> None:
    replay = _trace_requirement("R1-REPLAY")
    rollout = _trace_requirement("R1-LIVE-ROLLOUT")

    for path in (
        "scripts/smc_exit_signal_replay.py",
        "scripts/generate_smc_exit_signal_tv_fixture.py",
        "tests/fixtures/pine/smc_exit_signal_r1_fixture.pine",
        "artifacts/governance/smc_exit_signal_replay_preflight.json",
        "artifacts/governance/smc_exit_signal_tradingview_fixture_manifest.json",
        "artifacts/governance/smc_exit_signal_tradingview_replay_2026-07-29.json",
        "artifacts/governance/smc_r1_live_rollout_evidence_2026-07-29.json",
    ):
        assert path in replay["evidence"]
    assert replay["status"] == "complete"
    assert replay["openGates"] == []
    assert rollout["status"] == "complete"
    assert rollout["openGates"] == []
    assert LIVE_ROLLOUT_EVIDENCE.relative_to(ROOT).as_posix() in rollout["evidence"]
