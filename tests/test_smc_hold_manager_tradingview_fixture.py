"""Contracts for the generated Hold Manager TradingView replay fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.generate_smc_hold_manager_tv_fixture import (
    CASE_IDS,
    FIXTURE,
    MANIFEST,
    SOURCE,
    build_fixture,
    build_manifest,
)
from scripts.smc_bus_manifest import SURFACE_DEFINITIONS

ROOT = Path(__file__).resolve().parents[1]
COMPILE_EVIDENCE = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_fixture_compile_2026-07-27.json"
)


def _fixture_and_manifest() -> tuple[str, dict[str, object]]:
    source = SOURCE.read_text(encoding="utf-8")
    fixture = build_fixture(source)
    return fixture, build_manifest(source, fixture)


def test_generated_fixture_and_manifest_are_current() -> None:
    fixture, manifest = _fixture_and_manifest()

    assert FIXTURE.read_text(encoding="utf-8") == fixture
    assert json.loads(MANIFEST.read_text(encoding="utf-8")) == manifest


def test_fixture_is_source_pinned_and_explicitly_non_product() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    fixture, manifest = _fixture_and_manifest()
    source_hash = hashlib.sha256(source.encode()).hexdigest()

    assert f"SHA256 {source_hash}" in fixture
    assert "TEST ONLY — DO NOT PUBLISH OR USE FOR TRADING" in fixture
    assert manifest["canonicalSource"]["sha256"] == source_hash
    assert manifest["fixture"]["surfaceClass"] == (
        "test_only_not_managed_not_publishable"
    )
    assert FIXTURE.is_relative_to(ROOT / "tests" / "fixtures")
    assert FIXTURE.name not in {
        definition.file for definition in SURFACE_DEFINITIONS
    }


def test_fixture_covers_the_exact_twenty_case_contract() -> None:
    fixture, manifest = _fixture_and_manifest()
    cases = manifest["cases"]

    assert manifest["caseCount"] == 20
    assert [case["caseId"] for case in cases] == list(CASE_IDS)
    assert all(case["tradingViewStatus"] == "pending" for case in cases)
    assert [case["requiredTimeframe"] for case in cases].count("1D") == 1
    assert next(
        case for case in cases if case["caseId"] == "R2.4-11"
    )["variants"] == ["NONE", "ARMED", "IN_TRADE", "CLOSED"]
    stale_case = next(case for case in cases if case["caseId"] == "R2.4-17")
    assert stale_case["canonicalCoverage"] == (
        "blocked_missing_canonical_stale_context_diagnostic"
    )
    for case_id in CASE_IDS:
        assert f'"{case_id}"' in fixture


def test_fixture_rewires_every_external_runtime_feed() -> None:
    fixture, manifest = _fixture_and_manifest()

    assert "float src_schema = fixture_schema" in fixture
    assert "fixture_high >= hold.entry_price" in fixture
    assert "fixture_low <= stop_before_management" in fixture
    assert "float atr = fixture_atr" in fixture
    assert 'plot(ctx_profile_stale ? 1 : 0, "HM ContextStale"' in fixture
    assert 'plot(ctx_event_block ? 1 : 0, "HM EventWarning"' in fixture
    assert 'plot(fixture_exit_count, "Fixture HM_EXIT_ANY Count"' in fixture
    assert any(
        "not the canonical saved script" in limitation
        for limitation in manifest["limitations"]
    )
    assert any(
        "not TradingView server alert delivery" in limitation
        for limitation in manifest["limitations"]
    )
    assert any(
        "canonical stale Micro-Profile observability" in gate
        for gate in manifest["openGates"]
    )


def test_manifest_does_not_claim_unexecuted_tradingview_evidence() -> None:
    _fixture, manifest = _fixture_and_manifest()

    assert manifest["status"] == "fixture_ready_execution_pending"
    assert all(
        case["tradingViewStatus"] == "pending" for case in manifest["cases"]
    )
    assert all(
        "entryEpochMs" not in case["expectedCheckpointDiagnostics"]
        for case in manifest["cases"]
    )


def test_tradingview_compile_evidence_is_bounded_and_hash_pinned() -> None:
    _fixture, manifest = _fixture_and_manifest()
    evidence = json.loads(COMPILE_EVIDENCE.read_text(encoding="utf-8"))

    assert evidence["scope"] == (
        "Generated R2.4 fixture compile only; not replay-case or "
        "server-alert evidence"
    )
    assert (
        evidence["canonicalSource"]["sha256"]
        == manifest["canonicalSource"]["sha256"]
    )
    assert evidence["fixture"]["sha256"] == manifest["fixture"]["sha256"]
    assert evidence["fixture"]["savedStatus"] == "not_saved_test_only"
    assert evidence["tradingView"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["compileDiagnostics"] == []
    assert evidence["tradingView"]["addToChartStatus"] == "passed"
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True
    assert evidence["replay"]["status"] == "pending"
    assert evidence["replay"]["completedCaseIds"] == []
    assert evidence["replay"]["pendingCaseIds"] == list(CASE_IDS)
