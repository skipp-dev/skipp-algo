"""Tests for the F2 promotion-gate orchestrator CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_run_promotion_gate import main, run_promotion_gate
from scripts.f2_experiment_spec import load_f2_spec


REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_SPEC = REPO_ROOT / "artifacts" / "experiments" / "f2_contextual_promotion.json"


# ---------------------------------------------------------------------------
# Synthetic benchmark-artifact fixture builder
# ---------------------------------------------------------------------------


def _summary(
    *,
    symbol: str,
    n_events: int,
    hit_rate: float,
    brier: float,
    ece: float,
) -> dict:
    """Build a minimal scoring summary the load_benchmark loader accepts."""
    return {
        "symbol": symbol,
        "timeframe": "15m",
        "scoring": {
            "n_events": n_events,
            "brier_score": brier,
            "log_score": 0.70,
            "hit_rate": hit_rate,
            "families_present": ["BOS"],
            "family_metrics": {
                "BOS": {
                    "n_events": n_events,
                    "brier_score": brier,
                    "hit_rate": hit_rate,
                },
            },
            "calibration": {
                "method": "platt_scaling",
                "calibrated_brier_score": brier,
                "calibrated_ece": ece,
                "raw_ece": ece + 0.01,
            },
            "stratified_calibration_summary": {"dimensions_present": ["session"]},
            "contextual_calibration_summary": {
                "dimensions_present": ["session"],
                "best_dimension_by_adjusted_brier": "session",
                "best_dimension_by_adjusted_ece": "session",
            },
        },
        "ensemble_quality": {"score": 75.0, "tier": "high"},
        "stratification_coverage": {
            "dimensions_present": ["session"],
            "populated_bucket_count": 3,
        },
        "warnings": [],
    }


def _make_arm_dir(
    base: Path,
    *,
    arm_name: str,
    n_events: int,
    hit_rate: float,
    brier: float,
    ece: float,
) -> Path:
    """Materialize a benchmark_run_manifest + scoring summary on disk."""
    arm_dir = base / arm_name
    arm_dir.mkdir(parents=True, exist_ok=True)
    pair_dir = arm_dir / "AAPL_15m"
    pair_dir.mkdir(exist_ok=True)
    summary_path = pair_dir / "scoring_summary.json"
    summary_path.write_text(
        json.dumps(_summary(
            symbol="AAPL",
            n_events=n_events,
            hit_rate=hit_rate,
            brier=brier,
            ece=ece,
        )),
        encoding="utf-8",
    )
    manifest = {
        "pair_runs": [
            {"summary_path": "AAPL_15m/scoring_summary.json"},
        ],
    }
    (arm_dir / "benchmark_run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return arm_dir


# ---------------------------------------------------------------------------
# run_promotion_gate end-to-end
# ---------------------------------------------------------------------------


def test_run_promotion_gate_promotes_on_strong_treatment(tmp_path: Path) -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    control = _make_arm_dir(
        tmp_path, arm_name="control",
        n_events=800, hit_rate=0.55, brier=0.22, ece=0.12,
    )
    treatment = _make_arm_dir(
        tmp_path, arm_name="treatment",
        n_events=800, hit_rate=0.64, brier=0.18, ece=0.08,
    )
    report = run_promotion_gate(
        spec=spec,
        control_dir=control,
        treatment_dir=treatment,
        rollback_history=[],
    )
    assert report["schema_version"] == 1
    assert report["decision"] == "promote"
    assert report["actions"]
    assert report["sprt"]["decision"] == "accept_h1"


def test_run_promotion_gate_rolls_back_on_sprt_h0(tmp_path: Path) -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    control = _make_arm_dir(
        tmp_path, arm_name="control",
        n_events=800, hit_rate=0.55, brier=0.18, ece=0.10,
    )
    treatment = _make_arm_dir(
        tmp_path, arm_name="treatment",
        n_events=800, hit_rate=0.45, brier=0.25, ece=0.15,
    )
    report = run_promotion_gate(
        spec=spec,
        control_dir=control,
        treatment_dir=treatment,
        rollback_history=[],
    )
    assert report["decision"] == "rollback"
    assert "SPRT accepted H0" in report["reason"]


def test_run_promotion_gate_rolls_back_on_consecutive_worse_runs(tmp_path: Path) -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    control = _make_arm_dir(
        tmp_path, arm_name="control",
        n_events=800, hit_rate=0.58, brier=0.18, ece=0.10,
    )
    treatment = _make_arm_dir(
        tmp_path, arm_name="treatment",
        n_events=800, hit_rate=0.59, brier=0.18, ece=0.10,
    )
    report = run_promotion_gate(
        spec=spec,
        control_dir=control,
        treatment_dir=treatment,
        rollback_history=[0.01, 0.02],  # two consecutive worse on calibrated_brier
    )
    assert report["decision"] == "rollback"
    assert report["rollback_triggered"] is True


def test_run_promotion_gate_insufficient_data(tmp_path: Path) -> None:
    spec = load_f2_spec(SHIPPED_SPEC)
    control = _make_arm_dir(
        tmp_path, arm_name="control",
        n_events=50, hit_rate=0.55, brier=0.20, ece=0.10,
    )
    treatment = _make_arm_dir(
        tmp_path, arm_name="treatment",
        n_events=50, hit_rate=0.65, brier=0.18, ece=0.08,
    )
    report = run_promotion_gate(
        spec=spec,
        control_dir=control,
        treatment_dir=treatment,
        rollback_history=[],
    )
    assert report["decision"] == "insufficient_data"
    assert report["actions"] == []


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------


def test_cli_returns_0_on_promote(tmp_path: Path) -> None:
    control = _make_arm_dir(tmp_path, arm_name="ctrl",
                            n_events=800, hit_rate=0.55, brier=0.22, ece=0.12)
    treatment = _make_arm_dir(tmp_path, arm_name="treat",
                              n_events=800, hit_rate=0.64, brier=0.18, ece=0.08)
    output = tmp_path / "report.json"
    rc = main([
        "--spec", str(SHIPPED_SPEC),
        "--control-dir", str(control),
        "--treatment-dir", str(treatment),
        "--output", str(output),
    ])
    assert rc == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["decision"] == "promote"


def test_cli_returns_2_on_rollback(tmp_path: Path) -> None:
    control = _make_arm_dir(tmp_path, arm_name="ctrl",
                            n_events=800, hit_rate=0.55, brier=0.18, ece=0.10)
    treatment = _make_arm_dir(tmp_path, arm_name="treat",
                              n_events=800, hit_rate=0.45, brier=0.25, ece=0.15)
    rc = main([
        "--spec", str(SHIPPED_SPEC),
        "--control-dir", str(control),
        "--treatment-dir", str(treatment),
    ])
    assert rc == 2


def test_cli_returns_1_on_missing_dir(tmp_path: Path) -> None:
    control = _make_arm_dir(tmp_path, arm_name="ctrl",
                            n_events=800, hit_rate=0.55, brier=0.22, ece=0.12)
    rc = main([
        "--spec", str(SHIPPED_SPEC),
        "--control-dir", str(control),
        "--treatment-dir", str(tmp_path / "does-not-exist"),
    ])
    assert rc == 1


def test_cli_loads_rollback_history(tmp_path: Path) -> None:
    control = _make_arm_dir(tmp_path, arm_name="ctrl",
                            n_events=800, hit_rate=0.58, brier=0.18, ece=0.10)
    treatment = _make_arm_dir(tmp_path, arm_name="treat",
                              n_events=800, hit_rate=0.59, brier=0.18, ece=0.10)
    history_path = tmp_path / "history.json"
    history_path.write_text(json.dumps([0.01, 0.02]), encoding="utf-8")
    output = tmp_path / "report.json"
    rc = main([
        "--spec", str(SHIPPED_SPEC),
        "--control-dir", str(control),
        "--treatment-dir", str(treatment),
        "--rollback-history", str(history_path),
        "--output", str(output),
    ])
    assert rc == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["rollback_triggered"] is True
    assert report["rollback_history_len"] == 2
