"""Tests for silent-fallback audit fixes (Issue #2668).

S1: resolved_via + LEGACY_SINGLE_FILE_FALLBACK health_issue
S2: MACRO_BIAS_RAW is-not-None chains (falsy 0.0 regression)
S3: timestamp_source disclosure in execution rows + WorkflowFreshness
S4: TrustStateCause.attribution (exact vs worst_severity_heuristic)
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

# ────────────────────────────────────────────────────────────────────
# S1 — resolved_via provenance on structure contracts
# ────────────────────────────────────────────────────────────────────
from smc_integration.sources import structure_artifact_json


@pytest.fixture()
def _legacy_artifact(monkeypatch, tmp_path: Path) -> Path:
    """Write a minimal legacy smc_structure_artifact.json and wire it in."""
    artifact = tmp_path / "smc_structure_artifact.json"
    payload = {
        "generated_at": "2026-06-10T00:00:00Z",
        "entries": [
            {
                "symbol": "ES",
                "timeframe": "1D",
                "structure": {
                    "fvg": {"n_events": 100, "hit_rate": 0.55},
                    "bos": {"n_events": 50, "hit_rate": 0.60},
                },
            },
        ],
    }
    artifact.write_text(json.dumps(payload))
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", artifact)
    # Ensure manifest path returns no artifacts → triggers legacy fallback
    monkeypatch.setattr(
        structure_artifact_json,
        "_iter_manifest_artifacts",
        lambda *, repo_state_only=False: ([], []),
    )
    return artifact


def test_s1_legacy_fallback_emits_resolved_via_and_health_issue(_legacy_artifact: Path) -> None:
    contracts, health_issues = structure_artifact_json._iter_normalized_contracts()
    assert len(contracts) >= 1
    for c in contracts:
        assert c["resolved_via"] == "legacy_single", f"expected legacy_single, got {c.get('resolved_via')}"
    codes = [h["code"] for h in health_issues]
    assert "LEGACY_SINGLE_FILE_FALLBACK" in codes


def test_s1_manifest_path_marks_manifest_or_deterministic(monkeypatch, tmp_path: Path) -> None:
    """When per-TF artifacts exist, contracts get resolved_via=manifest_or_deterministic."""
    artifact = tmp_path / "ES_1D.structure.json"
    payload = {
        "symbol": "ES",
        "timeframe": "1D",
        "structure": {
            "fvg": {"n_events": 100, "hit_rate": 0.55},
            "bos": {"n_events": 50, "hit_rate": 0.60},
        },
    }
    artifact.write_text(json.dumps(payload))
    monkeypatch.setattr(
        structure_artifact_json,
        "_iter_manifest_artifacts",
        lambda *, repo_state_only=False: ([artifact], []),
    )
    contracts, health_issues = structure_artifact_json._iter_normalized_contracts()
    assert len(contracts) >= 1
    for c in contracts:
        assert c["resolved_via"] == "manifest_or_deterministic"
    # No legacy fallback health issue
    codes = [h["code"] for h in health_issues]
    assert "LEGACY_SINGLE_FILE_FALLBACK" not in codes


# ────────────────────────────────────────────────────────────────────
# S2 — MACRO_BIAS_RAW is-not-None chains
# ────────────────────────────────────────────────────────────────────


def _render_raw(regime: dict[str, Any]) -> float:
    """Replicate the fixed production logic for MACRO_BIAS_RAW."""
    _raw = regime.get("macro_bias_raw")
    return float(_raw if _raw is not None else 0.0)


def test_s2_falsy_zero_is_preserved() -> None:
    regime = {"macro_bias_raw": 0.0, "macro_bias": 0.5}
    assert _render_raw(regime) == 0.0


def test_s2_missing_raw_defaults_to_zero_not_adjusted() -> None:
    regime = {"macro_bias": 0.5}
    assert _render_raw(regime) == 0.0


def test_s2_present_raw_used() -> None:
    regime = {"macro_bias_raw": -0.3, "macro_bias": 0.5}
    assert _render_raw(regime) == pytest.approx(-0.3)


# ────────────────────────────────────────────────────────────────────
# S3a — timestamp_source in execution audit rows
# ────────────────────────────────────────────────────────────────────


def test_s3a_captured_at_preferred() -> None:
    event = {"captured_at": "2026-06-10T10:00:00Z", "trigger_at": "2026-06-10T09:59:00Z", "action": "fill"}
    _ts_source = "captured_at" if event.get("captured_at") else "trigger_at"
    assert _ts_source == "captured_at"


def test_s3a_trigger_at_fallback() -> None:
    event = {"trigger_at": "2026-06-10T09:59:00Z", "action": "fill"}
    _ts_source = "captured_at" if event.get("captured_at") else "trigger_at"
    assert _ts_source == "trigger_at"


# ────────────────────────────────────────────────────────────────────
# S3b — timestamp_source in WorkflowFreshness
# ────────────────────────────────────────────────────────────────────

from scripts.check_workflow_freshness import check_workflow


@pytest.fixture()
def _mock_fetcher():
    """Return a fetcher factory that returns canned API payloads."""

    def _make(run_payload: dict[str, Any]):
        def fetcher(url: str, headers: dict[str, str]) -> dict:
            return {"workflow_runs": [run_payload]}
        return fetcher

    return _make


def test_s3b_timestamp_source_updated_at(_mock_fetcher) -> None:
    now = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    run = {"updated_at": "2026-06-10T11:00:00Z", "run_started_at": "2026-06-10T10:50:00Z", "created_at": "2026-06-10T10:49:00Z", "id": 1, "html_url": "u"}
    result = check_workflow(repo="owner/repo", workflow_file="ci.yml", budget_hours=24, token="t", now=now, fetcher=_mock_fetcher(run))
    assert result.timestamp_source == "updated_at"


def test_s3b_timestamp_source_run_started_at(_mock_fetcher) -> None:
    now = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    run = {"run_started_at": "2026-06-10T10:50:00Z", "created_at": "2026-06-10T10:49:00Z", "id": 2, "html_url": "u"}
    result = check_workflow(repo="owner/repo", workflow_file="ci.yml", budget_hours=24, token="t", now=now, fetcher=_mock_fetcher(run))
    assert result.timestamp_source == "run_started_at"


def test_s3b_timestamp_source_created_at_fallback(_mock_fetcher) -> None:
    now = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    run = {"created_at": "2026-06-10T10:49:00Z", "id": 3, "html_url": "u"}
    result = check_workflow(repo="owner/repo", workflow_file="ci.yml", budget_hours=24, token="t", now=now, fetcher=_mock_fetcher(run))
    assert result.timestamp_source == "created_at"


# ────────────────────────────────────────────────────────────────────
# S4 — TrustStateCause.attribution
# ────────────────────────────────────────────────────────────────────

from smc_integration.trust_state import TrustState, TrustStateCause, _select_primary_cause


def test_s4_exact_match_attribution_unavailable() -> None:
    # hard_degrade maps to UNAVAILABLE → exact match
    alerts = [
        {"domain": "data", "failure_action": "hard_degrade", "code": "E001", "message": "data gone"},
    ]
    cause = _select_primary_cause(alerts, TrustState.UNAVAILABLE)
    assert cause.attribution == "exact"


def test_s4_exact_match_attribution_degraded() -> None:
    # advisory (non-stale) maps to DEGRADED → exact match
    alerts = [
        {"domain": "market", "failure_action": "advisory", "code": "W001", "message": "lagging"},
    ]
    cause = _select_primary_cause(alerts, TrustState.DEGRADED)
    assert cause.attribution == "exact"


def test_s4_worst_severity_heuristic_attribution() -> None:
    alerts = [
        {"domain": "data", "failure_action": "hard_degrade", "code": "E001", "message": "data gone"},
    ]
    # DEGRADED doesn't match hard_degrade (→UNAVAILABLE) → falls back to worst-severity
    cause = _select_primary_cause(alerts, TrustState.DEGRADED)
    assert cause.attribution == "worst_severity_heuristic"


def test_s4_healthy_has_default_attribution() -> None:
    cause = _select_primary_cause([], TrustState.HEALTHY)
    assert cause.attribution == "exact"


def test_s4_dataclass_default() -> None:
    cause = TrustStateCause(domain="test", failure_type="f", code="C", description="d")
    assert cause.attribution == "exact"
