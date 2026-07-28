"""Contracts for the generated Hold Manager TradingView replay fixture."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.generate_smc_hold_manager_tv_fixture import (
    CASE_IDS,
    FIXTURE,
    MANIFEST,
    SOURCE,
    build_fixture,
    build_manifest,
    freeze_library_pin,
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
    source_hash = hashlib.sha256(freeze_library_pin(source).encode()).hexdigest()

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


def test_generated_harness_exposes_its_diagnostics_in_the_data_window() -> None:
    """The twenty-case gate has to be readable to be executable.

    TradingView renders a ``display.none`` plot nowhere — "the script calculates
    the plot values, but does not display them in the script pane, status line,
    or Data Window" (Pine v6 reference). Inherited verbatim from the canonical,
    that made every checkpoint value in the R2.4 protocol unobservable: not by
    an operator, not by an automated driver. The harness is test-only, so it
    exposes them; hiding them again would silently re-close the gate.
    """

    fixture, _manifest = _fixture_and_manifest()

    assert "display.none" not in fixture, (
        "a harness diagnostic is hidden again — TradingView shows display.none "
        "plots nowhere, so the twenty-case gate cannot be read"
    )
    for series in (
        "HM StateCode",
        "HM PlanGeneration",
        "HM EntryEpochMs",
        "HM ProtectedHigh",
        "HM TerminalExitCode",
        "HM TerminalExitEpochMs",
        "HM NewPlanBlocked",
        "Fixture HM_ENTRY Count",
        "Fixture HM_EXIT_ANY Count",
    ):
        assert f'"{series}", display = display.data_window' in fixture, series


def test_canonical_keeps_its_diagnostics_hidden() -> None:
    """Only the test harness is made observable — the product surface is not."""

    source = SOURCE.read_text(encoding="utf-8")

    assert "display = display.none" in source
    assert "display.data_window" not in source, (
        "the canonical indicator is a product surface; exposing its internals "
        "in the Data Window is a deliberate decision, not a side effect of "
        "regenerating the test harness"
    )


def test_generated_harness_reads_no_micro_profile_field() -> None:
    """Premise of the frozen library pin.

    ``freeze_library_pin`` may only hold the harness steady across automated
    library republishes because the harness rewires every micro-profile input
    to a deterministic fixture series.  The moment a generated harness reads
    ``mp.`` again, the frozen pin would silently serve it stale library data —
    so fail here instead.
    """

    fixture, _manifest = _fixture_and_manifest()

    assert "mp." not in fixture, (
        "The generated R2.4 harness now reads a micro-profile field. Drop the "
        "frozen HARNESS_LIBRARY_PIN and let the pin track the canonical again "
        "(and re-capture the TradingView compile evidence)."
    )


def test_library_republish_does_not_churn_the_harness() -> None:
    """A refresh-only pin bump must leave fixture and manifest untouched.

    ``smc-library-refresh`` rewrites the canonical import three times per
    trading day and cannot regenerate this harness (its pin loop excludes
    ``tests/``).  Without this decoupling every refresh would strand the
    committed fixture, manifest and compile evidence on a stale source hash.
    """

    source = SOURCE.read_text(encoding="utf-8")
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

    assert build_fixture(republished) == build_fixture(source)
    assert build_manifest(
        republished, build_fixture(republished)
    ) == build_manifest(source, build_fixture(source))


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


def _assert_compile_evidence_matches_or_declares_supersession(
    evidence: dict, manifest: dict
) -> None:
    """The compile evidence may lag the harness — but never silently.

    Regenerating the harness (2026-07-28: diagnostics moved to the Data Window
    so the gate is readable at all) invalidates a recorded TradingView compile.
    Re-hashing the evidence would claim a compile that never happened, so the
    artifact instead keeps the hash it really covers and names its successor.
    """

    fixture_sha = manifest["fixture"]["sha256"]
    recorded = evidence["fixture"]["sha256"]
    if recorded == fixture_sha:
        assert "supersededBySha256" not in evidence["fixture"], (
            "evidence matches the current harness but still declares a successor"
        )
        return

    assert evidence["fixture"].get("supersededBySha256") == fixture_sha, (
        "The compile evidence no longer covers the committed harness. Record "
        "the successor hash under fixture.supersededBySha256 (and re-capture "
        "the compile) instead of silently re-hashing what was never compiled: "
        f"evidence={recorded[:12]} harness={fixture_sha[:12]}"
    )
    assert evidence["fixture"].get("recaptureRequired") is True
    assert any(
        "re-capture" in limitation.lower() for limitation in evidence["limitations"]
    ), "a superseded compile must say so in its limitations"


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
    _assert_compile_evidence_matches_or_declares_supersession(evidence, manifest)
    assert evidence["fixture"]["savedStatus"] == "not_saved_test_only"
    assert evidence["tradingView"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["compileDiagnostics"] == []
    assert evidence["tradingView"]["addToChartStatus"] == "passed"
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True
    assert evidence["replay"]["status"] == "pending"
    assert evidence["replay"]["completedCaseIds"] == []
    assert evidence["replay"]["pendingCaseIds"] == list(CASE_IDS)
