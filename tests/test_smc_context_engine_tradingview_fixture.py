"""Contracts for the private R3 Context Engine TradingView runtime fixture."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_smc_context_engine_tv_fixture import (
    CASES,
    FIXTURE,
    MANIFEST,
    SOURCE,
    build_fixture,
    build_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
ROLLOUT = ROOT / "automation" / "tradingview" / "config" / "consumer-rollout.json"
TRACE = ROOT / "artifacts" / "governance" / "pine_extended_migration_traceability.json"
EVIDENCE = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_context_engine_tradingview_replay_2026-07-29.json"
)


def _trace_requirement(requirement_id: str) -> dict:
    payload = json.loads(TRACE.read_text(encoding="utf-8"))
    return next(
        requirement
        for phase in payload["phases"]
        for requirement in phase["requirements"]
        if requirement["id"] == requirement_id
    )


def test_generated_fixture_and_manifest_are_current() -> None:
    fixture = build_fixture()

    assert FIXTURE.read_text(encoding="utf-8") == fixture
    assert json.loads(MANIFEST.read_text(encoding="utf-8")) == build_manifest(fixture)
    assert "SMC Context Engine R3 Fixture TEST ONLY" in fixture
    assert "Canonical source SHA-256:" in fixture
    assert 'runtime.error("R3 fixture mismatch' in fixture


def test_fixture_is_the_canonical_source_without_library_exports() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    fixture = FIXTURE.read_text(encoding="utf-8")

    for seam in (
        "_build_sweep_from_inputs",
        "_build_pool_from_inputs",
        "_build_session_from_inputs",
        "_aggregate_context",
    ):
        assert source.count(f"{seam}(") >= 2
        assert fixture.count(f"{seam}(") == source.count(f"{seam}(") + 1
    assert 'library("smc_context_engine_private"' not in fixture
    assert "\nexport " not in fixture
    assert 'indicator("SMC Context Engine R3 Fixture TEST ONLY"' in fixture


def test_live_builders_and_fixture_share_the_private_runtime_seams() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert "_build_sweep_from_inputs(high, low, close, volume" in source
    assert "_build_pool_from_inputs(high, low, close, pivot_high, pivot_low" in source
    assert "_build_session_from_inputs(structure, imbalance, time, high, low" in source
    assert "_aggregate_context(structure, imbalance, zone, sweep, pool, session_frame)" in source


def test_manifest_covers_all_required_runtime_domains() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cases = manifest["cases"]

    assert manifest["caseCount"] == len(CASES) == 15
    assert {case["domain"] for case in cases} == {
        "sweep",
        "pool",
        "session",
        "context",
    }
    assert {case["caseId"] for case in cases} == {runtime_case.case_id for runtime_case in CASES}
    assert all(case["tradingViewStatus"] == "pending" for case in cases)
    assert all(case["expectedDiagnostics"] for case in cases)


def test_fixture_is_not_a_managed_or_publishable_surface() -> None:
    fixture = FIXTURE.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rollout = ROLLOUT.read_text(encoding="utf-8")

    assert FIXTURE.name not in rollout
    assert manifest["surfaceClass"] == "test_only_not_managed_not_publishable"
    assert manifest["gateStatus"] == "partial"
    assert "DO NOT PUBLISH" in fixture


def test_private_tradingview_evidence_closes_the_r3_gate() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    cases = evidence["results"]["cases"]

    assert evidence["canonicalLibrary"]["publishedVersion"] == 4
    assert evidence["canonicalLibrary"]["postPublishNextOfferedVersion"] == 5
    assert evidence["canonicalLibrary"]["compileStatus"] == "passed"
    assert evidence["fixture"]["publicationStatus"] == "not_published"
    assert evidence["fixture"]["compileStatus"] == "passed"
    assert evidence["results"]["status"] == "passed"
    assert evidence["results"]["passedLogicalCases"] == len(cases) == 15
    assert evidence["results"]["failedLogicalCases"] == 0
    assert {case["caseId"] for case in cases} == {
        runtime_case.case_id for runtime_case in CASES
    }
    assert all(case["status"] == "passed" for case in cases)
    assert all(case["fixturePass"] == 1 for case in cases)
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True

    requirement = _trace_requirement("R3-REMAINING-FRAMES")
    publish = _trace_requirement("R3-PUBLISH")

    for path in (
        "scripts/generate_smc_context_engine_tv_fixture.py",
        "tests/fixtures/pine/smc_context_engine_r3_fixture.pine",
        "artifacts/governance/smc_context_engine_tradingview_fixture_manifest.json",
        EVIDENCE.relative_to(ROOT).as_posix(),
        "tests/test_smc_context_engine_tradingview_fixture.py",
    ):
        assert path in requirement["evidence"]
    assert requirement["status"] == "complete"
    assert requirement["openGates"] == []
    assert publish["status"] == "complete"
    assert publish["openGates"] == []
    assert EVIDENCE.relative_to(ROOT).as_posix() in publish["evidence"]
