"""Tests for the Pine Evidence Lane gate (WS1-FT-03).

These tests pin:

- the happy path: the in-process gate passes for the canonical fixtures;
- the gate's report shape (name/status/blocking/details);
- the drift detection path: a synthetic deviation fails the gate and surfaces
  per-scenario drift entries with stable codes;
- integration: the release-gates main() registers the evidence_lane gate
  among the structural CI-validatable gates.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from scripts.smc_pine_evidence_gate import build_evidence_lane_gate
from scripts.smc_pine_scenario_catalog import PINE_SCENARIO_CATALOG


def test_evidence_lane_gate_passes_for_canonical_fixtures() -> None:
    gate = build_evidence_lane_gate()

    assert gate["name"] == "evidence_lane"
    assert gate["status"] == "ok"
    assert gate["blocking"] is True
    details = gate["details"]
    assert details["scenarios_checked"] == len(PINE_SCENARIO_CATALOG)
    assert details["scenarios_passed"] == len(PINE_SCENARIO_CATALOG)
    assert details["scenarios_failed"] == 0
    assert details["failures"] == []
    assert len(details["scenario_results"]) == len(PINE_SCENARIO_CATALOG)


def test_evidence_lane_gate_results_in_catalog_order() -> None:
    gate = build_evidence_lane_gate()
    catalog_ids = [s.scenario_id for s in PINE_SCENARIO_CATALOG]
    result_ids = [row["scenario_id"] for row in gate["details"]["scenario_results"]]
    assert result_ids == catalog_ids


def test_evidence_lane_gate_per_scenario_row_shape() -> None:
    gate = build_evidence_lane_gate()
    for row in gate["details"]["scenario_results"]:
        assert set(row) == {
            "scenario_id",
            "name",
            "status",
            "drift_type",
            "primary_blocker",
            "expected_action",
            "observed_action",
            "drifts",
            "missing_keys",
        }
        assert row["status"] in {"ok", "fail"}
        assert row["expected_action"] == row["observed_action"]
        assert row["drifts"] == []
        assert row["missing_keys"] == []
        assert row["drift_type"] is None
        assert row["primary_blocker"] is None


def test_evidence_lane_gate_fails_on_synthetic_drift() -> None:
    """Force one scenario to drift and assert the gate fails with details."""
    real_build = build_evidence_lane_gate.__globals__["build_hero_state"]

    def drifting_build_hero_state(enrichment):
        result = real_build(enrichment)
        # Flip the action for the BOS scenario fixture only — detect by
        # checking the regime+freshness shape used by the BOS fixture.
        regime = (enrichment.get("regime") or {}).get("regime")
        freshness = (enrichment.get("signal_quality") or {}).get("SIGNAL_FRESHNESS")
        quality_tier = (enrichment.get("signal_quality") or {}).get("SIGNAL_QUALITY_TIER")
        if regime == "BULLISH" and freshness == "fresh" and quality_tier == "high":
            result = dict(result)
            result["HERO_ACTION"] = "WATCH"
        return result

    with mock.patch(
        "scripts.smc_pine_evidence_gate.build_hero_state",
        side_effect=drifting_build_hero_state,
    ):
        gate = build_evidence_lane_gate()

    assert gate["status"] == "fail"
    details = gate["details"]
    assert details["scenarios_failed"] >= 1
    failures = details["failures"]
    assert failures, "expected at least one drift failure"
    bos_failures = [f for f in failures if f["scenario_id"] == "ws1_bos_bullish_continuation"]
    assert bos_failures, "BOS scenario should be flagged as drifted"
    bos = bos_failures[0]
    assert bos["code"] == "PINE_EVIDENCE_DRIFT"
    drift_fields = {d["field"]: d for d in bos["drifts"]}
    assert "HERO_ACTION" in drift_fields
    assert drift_fields["HERO_ACTION"]["expected"] == "ACTIVE"
    assert drift_fields["HERO_ACTION"]["observed"] == "WATCH"


def test_release_gates_script_wires_evidence_lane_gate() -> None:
    """The release-gates script imports and registers the new gate."""
    source = Path("scripts/run_smc_release_gates.py").read_text(encoding="utf-8")
    assert "from scripts.smc_pine_evidence_gate import build_evidence_lane_gate" in source
    assert "gates.append(build_evidence_lane_gate())" in source
    # The gate must also be classified as CI-validatable so it actually
    # affects the structural pass.
    assert '"evidence_lane"' in source


def test_evidence_lane_gate_is_pure() -> None:
    """Calling the gate twice yields equal results (no hidden state)."""
    first = build_evidence_lane_gate()
    second = build_evidence_lane_gate()
    assert first == second
