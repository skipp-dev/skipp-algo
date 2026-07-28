"""Contracts for the generated Hold Manager TradingView replay fixture."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.generate_smc_hold_manager_tv_fixture import (
    CASE_IDS,
    CHECKPOINT_STEPS,
    FIXTURE,
    MANIFEST,
    RESET_VARIANT_EXPECTATIONS,
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
    / "smc_hold_manager_tradingview_fixture_compile_2026-07-28.json"
)
REPLAY_EVIDENCE = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_replay_2026-07-28.json"
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
        "canonical_stale_context_observability_plus_source_derived_harness"
    )
    assert stale_case["expectedContextDiagnostics"]["contextStale"] == 1
    assert manifest["physicalExecutionCount"] == 23
    assert {
        case["caseId"]: case["checkpointSteps"] for case in cases
    } == CHECKPOINT_STEPS
    assert {
        case["caseId"]: case["replayStopSteps"] for case in cases
    } == {
        case_id: [step + 1 for step in steps]
        for case_id, steps in CHECKPOINT_STEPS.items()
    }
    reset_case = next(case for case in cases if case["caseId"] == "R2.4-11")
    assert reset_case["variantExpectations"] == RESET_VARIANT_EXPECTATIONS
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
    assert '"Fixture Confirmed Step", display = display.none' in fixture
    assert "TEST ONLY — R2.4 READBACK (1.6)" in fixture
    assert '" | confirmed_step=" +' in fixture
    assert "str.tostring(fixture_confirmed_step)" in fixture
    assert "fixture_readback_new_plan_blocked" in fixture
    assert "fixture_readback_context_stale" in fixture
    assert "fixture_readback_event_warning" in fixture
    assert '"ENTRY=" + str.tostring(fixture_entry_count)' in fixture
    assert any(
        "not the canonical saved script" in limitation
        for limitation in manifest["limitations"]
    )
    assert any(
        "not TradingView server alert delivery" in limitation
        for limitation in manifest["limitations"]
    )
    assert not any(
        "stale Micro-Profile observability" in gate
        for gate in manifest["openGates"]
    )
    assert any(
        "twenty-three physical runs" in gate
        for gate in manifest["openGates"]
    )
    assert any(
        "explicit approval" in gate.lower()
        and "exact generated fixture SHA-256" in gate
        for gate in manifest["openGates"]
    )
    assert any(
        "newest replay bar unconfirmed" in limitation
        for limitation in manifest["limitations"]
    )


def test_delayed_entry_fixture_does_not_trigger_before_checkpoint() -> None:
    fixture, _manifest = _fixture_and_manifest()
    trade_case_block = fixture.split(
        "bool fixture_trade_case = ", maxsplit=1
    )[1].split("if fixture_trade_case", maxsplit=1)[0]

    assert '"R2.4-02"' not in trade_case_block
    assert 'if fixture_case == "R2.4-02"' in fixture
    assert "if fixture_step == 204" in fixture
    assert "else if fixture_step > 204" in fixture
    assert (
        """if fixture_step == 204
        fixture_open := 102.0
        fixture_high := 105.0
        fixture_low := 99.0
        fixture_close := 103.0"""
        in fixture
    )
    assert (
        """else if fixture_step > 204
        fixture_open := 104.0
        fixture_high := 105.0
        fixture_low := 101.0
        fixture_close := 104.0"""
        in fixture
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


def test_current_tradingview_compile_evidence_is_hash_pinned() -> None:
    _fixture, manifest = _fixture_and_manifest()
    evidence = json.loads(COMPILE_EVIDENCE.read_text(encoding="utf-8"))
    replay_evidence = json.loads(REPLAY_EVIDENCE.read_text(encoding="utf-8"))

    assert evidence["scope"] == (
        "Generated R2.4 fixture compile only; not replay-case or "
        "server-alert evidence"
    )
    assert (
        evidence["canonicalSource"]["sha256"]
        == replay_evidence["canonicalSource"]["sha256"]
    )
    assert (
        evidence["fixture"]["sha256"]
        == replay_evidence["fixture"]["sha256"]
    )
    assert evidence["fixture"]["sha256"] == manifest["fixture"]["sha256"]
    assert evidence["fixture"]["savedStatus"] == "saved_private_test_only"
    assert evidence["fixture"]["publicationStatus"] == "not_published"
    assert evidence["tradingView"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["compileDiagnostics"] == []
    assert evidence["tradingView"]["addToChartStatus"] == "passed"
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True
    assert evidence["replay"]["status"] == "recorded_separately"
    assert evidence["replay"]["evidence"].endswith(
        "smc_hold_manager_tradingview_replay_2026-07-28.json"
    )
