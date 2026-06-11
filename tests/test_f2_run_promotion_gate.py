"""Tests for the F2 promotion-gate orchestrator CLI."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from scripts.f2_experiment_spec import load_f2_spec
from scripts.f2_run_promotion_gate import main, run_promotion_gate

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_SPEC = REPO_ROOT / "artifacts" / "experiments" / "f2_contextual_promotion.json"


def _live_spec():
    """Return the shipped spec with ``status='live'``.

    The shipped spec sits at ``status='plumbing_only'`` while the
    audit-driven follow-up PRs (#43 frozen artifact, #44 paired-SPRT)
    are pending. Tests that exercise the *underlying* gate logic
    (promote / rollback / insufficient_data) need to override that
    guard so they keep verifying the math, not the guard.
    """
    return dataclasses.replace(load_f2_spec(SHIPPED_SPEC), status="live")


def _write_live_spec_copy(tmp_path: Path) -> Path:
    """Write a tmp copy of the shipped spec with ``status='live'``.

    Used by the CLI tests where we cannot pass a dataclass through.
    """
    spec_dict = json.loads(SHIPPED_SPEC.read_text(encoding="utf-8"))
    spec_dict["status"] = "live"
    out = tmp_path / "spec_live.json"
    out.write_text(json.dumps(spec_dict), encoding="utf-8")
    return out


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
    spec = _live_spec()
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
    # Status banner present and clean on a live spec.
    assert report["spec_status"] == "live"
    assert report["warnings"] == []


def test_run_promotion_gate_rolls_back_on_sprt_h0(tmp_path: Path) -> None:
    spec = _live_spec()
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
    spec = _live_spec()
    # W6-3: run_promotion_gate now includes the current run's delta in the
    # window evaluated by evaluate_rollback.  With rollback_history=[0.01]
    # (one prior bad day), the gate fires only when today's delta is also
    # positive (i.e. treatment is worse than control).  We make treatment
    # brier clearly higher to ensure a positive current delta.
    control = _make_arm_dir(
        tmp_path, arm_name="control",
        n_events=800, hit_rate=0.58, brier=0.18, ece=0.10,
    )
    treatment = _make_arm_dir(
        tmp_path, arm_name="treatment",
        n_events=800, hit_rate=0.57, brier=0.22, ece=0.12,  # clearly worse
    )
    report = run_promotion_gate(
        spec=spec,
        control_dir=control,
        treatment_dir=treatment,
        rollback_history=[0.01],  # one prior worse day; today's delta also > 0
    )
    assert report["decision"] == "rollback"
    assert report["rollback_triggered"] is True


def test_run_promotion_gate_insufficient_data(tmp_path: Path) -> None:
    spec = _live_spec()
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
    spec_path = _write_live_spec_copy(tmp_path)
    rc = main([
        "--spec", str(spec_path),
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
                              n_events=800, hit_rate=0.57, brier=0.22, ece=0.12)  # worse for rollback
    history_path = tmp_path / "history.json"
    # W6-3: rollback_history=[0.01] + current (treatment brier 0.22 > control 0.18 → delta>0)
    # = 2 consecutive worse runs → rollback fires (consecutive_worse_runs=2).
    history_path.write_text(json.dumps([0.01]), encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Spec-status guard (audit C1/C2/C3 follow-up)
# ---------------------------------------------------------------------------


def test_spec_status_plumbing_only_blocks_promote(tmp_path: Path) -> None:
    """spec.status='plumbing_only' coerces a promote decision to hold."""
    spec = dataclasses.replace(_live_spec(), status="plumbing_only")
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
    # Underlying SPRT/KPI math still says promote ...
    assert report["sprt"]["decision"] == "accept_h1"
    # ... but the guard demotes the surfaced decision to hold.
    assert report["decision"] == "hold"
    assert report["spec_status"] == "plumbing_only"
    assert any("plumbing_only" in w for w in report["warnings"])
    assert any("promote disabled" in a.lower() for a in report["actions"])


def test_spec_status_plumbing_only_keeps_rollback_path(tmp_path: Path) -> None:
    """spec.status='plumbing_only' does NOT mask a rollback decision."""
    spec = dataclasses.replace(_live_spec(), status="plumbing_only")
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
    # Warning still surfaced — operators must see the spec is non-live.
    assert any("plumbing_only" in w for w in report["warnings"])


def test_spec_status_warning_surfaces_for_hold_decision(tmp_path: Path) -> None:
    """A non-live spec attaches the banner even when the natural decision is hold."""
    spec = dataclasses.replace(_live_spec(), status="plumbing_only")
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
    assert report["spec_status"] == "plumbing_only"
    assert report["warnings"]


def test_cli_shipped_spec_promotes_under_live(tmp_path: Path) -> None:
    """With spec.status='live' and strong treatment, the gate promotes.

    Formerly pinned ``decision=hold`` while the spec was at
    ``plumbing_only``.  Now that spec is ``live`` (PR #2645), the same
    strong treatment should yield a promote decision.
    """
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
    assert report["spec_status"] == "live"
    assert report["decision"] == "promote"


# ---------------------------------------------------------------------------
# W6-3 — rollback history must include the current run's delta (wave 6)
# ---------------------------------------------------------------------------


def test_run_promotion_gate_includes_current_delta_in_rollback(tmp_path: Path) -> None:
    """W6-3: current run's delta must be appended to history before evaluate_promotion.

    Scenario: history has one entry already worse (delta > 0). The current
    run is also worse. With the off-by-one bug the gate would still need
    *another* bad run before triggering rollback. With the fix, the gate
    fires immediately (consecutive_worse_runs=2, history=[bad]+[bad_today]).
    """
    spec = _live_spec()
    # consecutive_worse_runs=2 in the shipped spec — we need exactly 2 bad deltas.
    assert spec.rollback_gate.consecutive_worse_runs == 2, (
        "test assumption: spec.rollback_gate.consecutive_worse_runs must be 2"
    )

    # Control arm: strong hit rate / good brier.
    # Treatment arm: slightly worse brier (delta > 0 = worse for calibrated_brier).
    # n_events >= min_events_per_arm (600) so evaluate_promotion passes the
    # insufficient_data guard and reaches the rollback check.
    control = _make_arm_dir(tmp_path, arm_name="ctrl",
                            n_events=700, hit_rate=0.60, brier=0.20, ece=0.08)
    treatment = _make_arm_dir(tmp_path, arm_name="treat",
                              n_events=700, hit_rate=0.55, brier=0.23, ece=0.10)

    # Pre-existing history: one worse day (treatment brier was higher yesterday).
    rollback_history_one_bad = [0.03]  # positive = treatment worse

    report = run_promotion_gate(
        spec=spec,
        control_dir=control,
        treatment_dir=treatment,
        rollback_history=rollback_history_one_bad,
    )
    # The gate should have included today's (also positive) delta.
    # If the current delta is positive the gate must trigger.
    assert report["rollback_history_includes_current_run"] is True
    assert report["rollback_history_len"] == 2  # yesterday + today
    # With two consecutive worse runs the rollback gate should fire.
    assert report["decision"] == "rollback", (
        f"expected rollback with 2 bad deltas; got decision={report['decision']!r}, "
        f"rollback_history_len={report['rollback_history_len']}"
    )


def test_run_promotion_gate_report_exposes_current_run_flag(tmp_path: Path) -> None:
    """W6-3: rollback_history_includes_current_run must always be present in report."""
    spec = _live_spec()
    control = _make_arm_dir(tmp_path, arm_name="ctrl",
                            n_events=800, hit_rate=0.60, brier=0.20, ece=0.08)
    treatment = _make_arm_dir(tmp_path, arm_name="treat",
                              n_events=800, hit_rate=0.64, brier=0.18, ece=0.07)
    report = run_promotion_gate(
        spec=spec,
        control_dir=control,
        treatment_dir=treatment,
        rollback_history=[],
    )
    assert "rollback_history_includes_current_run" in report
    assert "rollback_history_len" in report
