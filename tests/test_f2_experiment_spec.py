"""Tests for the F2 contextual-promotion experiment spec + gate evaluator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_experiment_spec import (
    SPEC_SCHEMA_VERSION,
    evaluate_promotion,
    evaluate_rollback,
    load_f2_spec,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_SPEC = REPO_ROOT / "artifacts" / "experiments" / "f2_contextual_promotion.json"


# ---------------------------------------------------------------------------
# Loader / shipped spec
# ---------------------------------------------------------------------------


def test_shipped_spec_loads_and_validates() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    assert spec.name == "f2-contextual-zone-priority-promotion"
    assert spec.control.label == "static_global_weights"
    assert spec.treatment.label.startswith("contextual_weights")
    assert spec.sprt.p0 == 0.55
    assert spec.sprt.p1 == 0.60
    assert spec.sprt.max_n == 600
    assert spec.rollback_gate.consecutive_worse_runs == 2
    assert spec.rollback_gate.comparison_metric == "calibrated_brier"
    assert spec.min_days == 30
    assert spec.min_events_per_arm == 600


def test_shipped_spec_artifacts_paths_resolved() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    assert spec.control_artifact == Path(
        "artifacts/reports/zone_priority_calibration.json"
    )
    assert spec.treatment_artifact == Path(
        "artifacts/reports/zone_priority_contextual_calibration.json"
    )


def test_load_rejects_unsupported_schema(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        load_f2_spec(bad)


def test_load_rejects_missing_required_fields(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"schema_version": SPEC_SCHEMA_VERSION, "name": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required key"):
        load_f2_spec(bad)


# ---------------------------------------------------------------------------
# Rollback gate
# ---------------------------------------------------------------------------


def test_rollback_does_not_trigger_with_short_history() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    # consecutive_worse_runs=2 in shipped spec
    assert evaluate_rollback([0.01], spec) is False
    assert evaluate_rollback([], spec) is False


def test_rollback_triggers_on_two_consecutive_worse_runs() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    assert evaluate_rollback([-0.01, 0.01, 0.02], spec) is True


def test_rollback_does_not_trigger_when_recovery_in_window() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    # Last two: [0.01, -0.01] -> not all positive
    assert evaluate_rollback([0.02, 0.03, 0.01, -0.01], spec) is False


# ---------------------------------------------------------------------------
# Promotion gate end-to-end
# ---------------------------------------------------------------------------


def _digest(
    sprt_decision: str,
    n: int,
    *,
    cb_delta: float = -0.01,
    ce_delta: float = -0.01,
    hr_delta: float = 0.0,
    k: int = 0,
    llr: float = 0.0,
) -> dict:
    return {
        "sprt": {"decision": sprt_decision, "n": n, "k": k, "llr": llr},
        "metrics": [
            {"metric": "calibrated_brier", "delta": cb_delta},
            {"metric": "calibrated_ece", "delta": ce_delta},
            {"metric": "hit_rate_pct", "delta": hr_delta},
        ],
    }


def test_promotion_blocks_on_thin_sample() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    out = evaluate_promotion(_digest("accept_h1", n=50), spec)
    assert out["decision"] == "insufficient_data"
    assert out["actions"] == ()


def test_promotion_promotes_when_sprt_h1_and_kpi_gate_ok() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    out = evaluate_promotion(
        _digest("accept_h1", n=800, cb_delta=-0.01, ce_delta=-0.01, hr_delta=0.5),
        spec,
    )
    assert out["decision"] == "promote"
    assert out["actions"] == spec.on_promote
    assert "SPRT accepted H1" in out["reason"]


def test_promotion_holds_when_sprt_h1_but_kpi_gate_fails() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    # Brier delta only -0.001 < -0.005 threshold
    out = evaluate_promotion(
        _digest("accept_h1", n=800, cb_delta=-0.001, ce_delta=-0.01),
        spec,
    )
    assert out["decision"] == "hold"
    assert "KPI gate not satisfied" in out["reason"]


def test_promotion_rolls_back_on_sprt_h0() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    out = evaluate_promotion(
        _digest("accept_h0", n=800, cb_delta=0.01),
        spec,
    )
    assert out["decision"] == "rollback"
    assert out["actions"] == spec.on_reject
    assert "SPRT accepted H0" in out["reason"]


def test_promotion_rolls_back_on_rollback_gate() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    out = evaluate_promotion(
        _digest("max_n_reached", n=800),
        spec,
        daily_deltas=[0.01, 0.02],  # two consecutive worse
    )
    assert out["decision"] == "rollback"
    assert "rollback_gate triggered" in out["reason"]


def test_promotion_holds_when_sprt_inconclusive_and_no_rollback() -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    out = evaluate_promotion(
        _digest("max_n_reached", n=800),
        spec,
    )
    assert out["decision"] == "hold"
    assert out["actions"] == ()
    assert "SPRT inconclusive" in out["reason"]


def test_rollback_validation_rejects_bad_consecutive() -> None:
    from scripts.f2_experiment_spec import RollbackGateSpec

    with pytest.raises(ValueError):
        RollbackGateSpec(consecutive_worse_runs=0, comparison_metric="x")
