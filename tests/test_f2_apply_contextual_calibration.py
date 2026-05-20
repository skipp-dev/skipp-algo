"""Tests for ``scripts/f2_apply_contextual_calibration.py``.

Plan reference: smc_improvement_plan_q3_q4_2026-04-20.md §2.3 F2 + §2.4 G3.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

import pytest

from scripts.f2_apply_contextual_calibration import (
    apply_contextual_calibration,
    _write_arm,
    blend_prob,
    rescore_pair,
)
from scripts.f2_experiment_spec import load_f2_spec
from scripts.f2_run_promotion_gate import run_promotion_gate
from scripts.smc_zone_priority_calibration import ContextualCalibrationResult

# ── Shared fixture builders ────────────────────────────────────────────────


def _write_ledger(
    pair_dir: Path, *, symbol: str, timeframe: str, events: list[dict[str, Any]]
) -> Path:
    """Write a minimal JSONL ledger compatible with read_event_ledger()."""
    pair_dir.mkdir(parents=True, exist_ok=True)
    path = pair_dir / f"events_{symbol}_{timeframe}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")))
            handle.write("\n")
    return path


def _make_event(
    *,
    event_id: str,
    family: str,
    predicted_prob: float,
    outcome: bool,
    session: str = "RTH",
    vol_regime: str = "NORMAL",
    timestamp: float = 0.0,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "symbol": "AAPL",
        "timeframe": "5m",
        "family": family,
        "timestamp": timestamp,
        "predicted_prob": predicted_prob,
        "outcome": outcome,
        "context": {"session": session, "vol_regime": vol_regime},
        "raw_score": None,
        "raw_score_name": None,
        "features": {},
        "outcome_extras": {},
    }


def _build_control_dir(tmp_path: Path, n_events: int = 50) -> Path:
    """Two pairs × n_events events with deterministic outcomes."""
    rng = random.Random(42)
    control_dir = tmp_path / "rolling" / "2026-04-23"
    for symbol, timeframe in (("AAPL", "5m"), ("MSFT", "15m")):
        events = []
        for i in range(n_events):
            family = ("BOS", "OB", "FVG", "SWEEP")[i % 4]
            session = ("RTH", "ETH", "KILLZONE")[i % 3]
            vol = ("LOW", "NORMAL", "HIGH")[i % 3]
            # Hit-rate ~ 0.55 on average; deterministic via seeded rng.
            outcome = rng.random() < (0.6 if family in ("BOS", "OB") else 0.5)
            events.append(_make_event(
                event_id=f"{symbol}-{timeframe}-{i}",
                family=family,
                predicted_prob=0.55,
                outcome=outcome,
                session=session,
                vol_regime=vol,
                timestamp=float(i),
            ))
        _write_ledger(control_dir / symbol / timeframe,
                      symbol=symbol, timeframe=timeframe, events=events)
    return control_dir


def _write_calibrations(tmp_path: Path) -> tuple[Path, Path]:
    """Plausible global + contextual calibration files."""
    global_path = tmp_path / "global_cal.json"
    global_path.write_text(json.dumps({
        "family_weights": {"OB": 0.82, "FVG": 0.61, "BOS": 0.71, "SWEEP": 0.55},
    }, sort_keys=True), encoding="utf-8")

    ctx_path = tmp_path / "contextual_cal.json"
    ctx_path.write_text(json.dumps({
        "global_weights": {"OB": 0.82, "FVG": 0.61, "BOS": 0.71, "SWEEP": 0.55},
        "promoted_buckets": ["session:RTH", "vol_regime:HIGH"],
        "contextual_weights": {
            "session": {
                "RTH": {"OB": 0.90, "FVG": 0.70, "BOS": 0.78, "SWEEP": 0.62},
            },
            "vol_regime": {
                "HIGH": {"OB": 0.85, "FVG": 0.65, "BOS": 0.74, "SWEEP": 0.60},
            },
        },
        "bucket_stats": {},
        "min_bucket_events": 30,
    }, sort_keys=True), encoding="utf-8")
    return global_path, ctx_path


# ── 4.1 Determinism ────────────────────────────────────────────────────────


def test_post_processor_is_byte_deterministic(tmp_path: Path) -> None:
    """Two identical runs must produce byte-identical output trees."""
    control_dir = _build_control_dir(tmp_path)
    global_path, ctx_path = _write_calibrations(tmp_path)

    def _run(out_root: Path) -> dict[str, str]:
        out_ctrl = out_root / "control"
        out_treat = out_root / "treatment"
        apply_contextual_calibration(
            control_dir=control_dir,
            contextual_cal_path=ctx_path,
            global_cal_path=global_path,
            output_dir_control=out_ctrl,
            output_dir_treatment=out_treat,
        )
        digests: dict[str, str] = {}
        for path in sorted([*out_root.rglob("*.json")]):
            digests[path.relative_to(out_root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        return digests

    a = _run(tmp_path / "run_a")
    b = _run(tmp_path / "run_b")
    assert a == b, "post-processor output must be byte-deterministic"
    assert a, "expected at least one output file"


# ── 4.2 Fallback ───────────────────────────────────────────────────────────


def test_empty_promoted_buckets_make_treatment_equal_to_control(tmp_path: Path) -> None:
    """No promoted buckets → treatment falls back to global → arms match."""
    control_dir = _build_control_dir(tmp_path)
    global_path, _ = _write_calibrations(tmp_path)

    # Build a contextual calibration with NO promoted buckets.
    ctx_path = tmp_path / "ctx_empty.json"
    ctx_path.write_text(json.dumps({
        "global_weights": {"OB": 0.82, "FVG": 0.61, "BOS": 0.71, "SWEEP": 0.55},
        "promoted_buckets": [],
        "contextual_weights": {},
        "bucket_stats": {},
        "min_bucket_events": 30,
    }, sort_keys=True), encoding="utf-8")

    out_ctrl = tmp_path / "out_ctrl"
    out_treat = tmp_path / "out_treat"
    apply_contextual_calibration(
        control_dir=control_dir,
        contextual_cal_path=ctx_path,
        global_cal_path=global_path,
        output_dir_control=out_ctrl,
        output_dir_treatment=out_treat,
    )

    # Compare every per-pair calibrated_brier — they must match exactly
    # (both arms use the same global weights through the same blend).
    ctrl_manifest = json.loads(
        (out_ctrl / "benchmark_run_manifest.json").read_text(encoding="utf-8")
    )
    treat_manifest = json.loads(
        (out_treat / "benchmark_run_manifest.json").read_text(encoding="utf-8")
    )
    assert ctrl_manifest["pair_runs"] == treat_manifest["pair_runs"]
    for run in ctrl_manifest["pair_runs"]:
        ctrl_summary = json.loads(
            (out_ctrl / run["summary_path"]).read_text(encoding="utf-8")
        )
        treat_summary = json.loads(
            (out_treat / run["summary_path"]).read_text(encoding="utf-8")
        )
        assert ctrl_summary["scoring"]["calibration"]["calibrated_brier_score"] == \
            pytest.approx(treat_summary["scoring"]["calibration"]["calibrated_brier_score"]), \
            f"empty-promotion fallback must produce identical arms ({run['summary_path']})"


# ── 4.3 Brier improvement on a synthetic, well-separated fixture ───────────


def test_treatment_arm_improves_brier_on_promoted_bucket_fixture(tmp_path: Path) -> None:
    """Synthetic events where the contextual bucket truly carries signal.

    All events live in promoted buckets (RTH session). Outcomes correlate
    strongly with family direction so the contextual weight (0.90 for OB)
    drives the treatment prediction much closer to the realised hit-rate
    than the global weight (0.82) does.
    """
    control_dir = tmp_path / "rolling" / "2026-04-23"
    events: list[dict[str, Any]] = []
    for i in range(60):
        # All RTH so the contextual bucket fires for every event.
        # Family OB: HR ~0.90 → contextual w=0.90 wins on Brier.
        outcome = (i % 10) < 9  # 90% outcome True
        events.append(_make_event(
            event_id=f"AAPL-5m-{i}",
            family="OB",
            predicted_prob=0.55,
            outcome=outcome,
            session="RTH",
            vol_regime="NORMAL",
            timestamp=float(i),
        ))
    _write_ledger(control_dir / "AAPL" / "5m",
                  symbol="AAPL", timeframe="5m", events=events)

    global_path = tmp_path / "global_cal.json"
    global_path.write_text(json.dumps({
        "family_weights": {"OB": 0.55, "FVG": 0.50, "BOS": 0.50, "SWEEP": 0.50},
    }), encoding="utf-8")

    ctx_path = tmp_path / "ctx_cal.json"
    ctx_path.write_text(json.dumps({
        "global_weights": {"OB": 0.55, "FVG": 0.50, "BOS": 0.50, "SWEEP": 0.50},
        "promoted_buckets": ["session:RTH"],
        "contextual_weights": {
            "session": {
                "RTH": {"OB": 0.90, "FVG": 0.50, "BOS": 0.50, "SWEEP": 0.50},
            },
        },
        "bucket_stats": {},
        "min_bucket_events": 30,
    }), encoding="utf-8")

    out_ctrl = tmp_path / "ctrl"
    out_treat = tmp_path / "treat"
    apply_contextual_calibration(
        control_dir=control_dir,
        contextual_cal_path=ctx_path,
        global_cal_path=global_path,
        output_dir_control=out_ctrl,
        output_dir_treatment=out_treat,
    )
    ctrl_summary = json.loads(
        (out_ctrl / "AAPL/5m/measurement_summary_AAPL_5m.json").read_text(encoding="utf-8")
    )
    treat_summary = json.loads(
        (out_treat / "AAPL/5m/measurement_summary_AAPL_5m.json").read_text(encoding="utf-8")
    )
    ctrl_brier = ctrl_summary["scoring"]["brier_score"]
    treat_brier = treat_summary["scoring"]["brier_score"]
    assert treat_brier < ctrl_brier - 0.01, (
        f"treatment Brier ({treat_brier:.4f}) should beat control Brier "
        f"({ctrl_brier:.4f}) by >0.01 on the synthetic fixture"
    )


# ── 4.4 End-to-end gate run ────────────────────────────────────────────────


def test_end_to_end_promotion_gate_runs_against_post_processed_dirs(
    tmp_path: Path,
) -> None:
    """The artifact dirs the post-processor writes must be consumable by
    f2_run_promotion_gate without raising."""
    control_dir = _build_control_dir(tmp_path, n_events=80)
    global_path, ctx_path = _write_calibrations(tmp_path)
    out_ctrl = tmp_path / "f2_ctrl"
    out_treat = tmp_path / "f2_treat"
    apply_contextual_calibration(
        control_dir=control_dir,
        contextual_cal_path=ctx_path,
        global_cal_path=global_path,
        output_dir_control=out_ctrl,
        output_dir_treatment=out_treat,
    )

    spec = load_f2_spec(Path("artifacts/experiments/f2_contextual_promotion.json"))
    report = run_promotion_gate(
        spec=spec,
        control_dir=out_ctrl,
        treatment_dir=out_treat,
        rollback_history=[],
    )
    assert report["decision"] in {"promote", "hold", "rollback", "insufficient_data"}
    assert report["decision"] != "skipped"  # the bug we're fixing


def test_write_arm_sanitizes_non_finite_metrics_to_null(tmp_path: Path) -> None:
    summary = {
        "schema_version": "1.0",
        "generated_at": 0.0,
        "generator": "tests",
        "symbol": "AAPL",
        "timeframe": "5m",
        "artifact_dir": "",
        "scoring": {
            "n_events": 0,
            "brier_score": float("nan"),
            "log_score": float("inf"),
            "hit_rate": float("-inf"),
            "families_present": ["OB"],
            "family_metrics": {
                "OB": {
                    "family": "OB",
                    "n_events": 0,
                    "brier_score": float("nan"),
                    "log_score": float("inf"),
                    "hit_rate": float("-inf"),
                }
            },
            "calibration": {},
            "stratified_calibration": {},
            "stratified_calibration_summary": {"dimensions_present": []},
            "contextual_calibration": {},
            "contextual_calibration_summary": {"dimensions_present": []},
        },
        "ensemble_quality": {},
        "stratification_coverage": {"dimensions_present": [], "populated_bucket_count": 0},
        "warnings": [],
    }

    manifest = _write_arm(
        tmp_path / "control",
        pair_summaries=[("AAPL", "5m", summary)],
        blend_alpha=1.0,
        arm_name="control",
    )

    manifest_text = (tmp_path / "control" / "benchmark_run_manifest.json").read_text(encoding="utf-8")
    summary_text = (tmp_path / "control" / "AAPL" / "5m" / "measurement_summary_AAPL_5m.json").read_text(encoding="utf-8")
    assert "NaN" not in manifest_text
    assert "Infinity" not in manifest_text
    assert "NaN" not in summary_text
    assert "Infinity" not in summary_text

    payload = json.loads(summary_text)
    assert payload["scoring"]["brier_score"] is None
    assert payload["scoring"]["log_score"] is None
    assert payload["scoring"]["hit_rate"] is None
    assert payload["scoring"]["family_metrics"]["OB"]["brier_score"] is None
    assert payload["scoring"]["family_metrics"]["OB"]["log_score"] is None
    assert payload["scoring"]["family_metrics"]["OB"]["hit_rate"] is None
    assert manifest["pair_runs"][0]["summary_path"] == "AAPL/5m/measurement_summary_AAPL_5m.json"


# ── Helper-level invariants ────────────────────────────────────────────────


def test_blend_prob_clamps_to_safety_band() -> None:
    assert blend_prob(0.99, 0.99) == pytest.approx(0.95)
    assert blend_prob(0.01, 0.01) == pytest.approx(0.05)
    assert blend_prob(0.5, 0.5) == pytest.approx(0.5)


def test_rescore_pair_force_global_makes_arms_identical(tmp_path: Path) -> None:
    pair_dir = tmp_path / "AAPL" / "5m"
    _write_ledger(pair_dir, symbol="AAPL", timeframe="5m", events=[
        _make_event(event_id="e1", family="OB", predicted_prob=0.55, outcome=True),
        _make_event(event_id="e2", family="FVG", predicted_prob=0.55, outcome=False),
    ])
    ledger = pair_dir / "events_AAPL_5m.jsonl"
    ctx = ContextualCalibrationResult(
        contextual_weights={"session": {"RTH": {"OB": 0.99, "FVG": 0.99,
                                                "BOS": 0.99, "SWEEP": 0.99}}},
        promoted_buckets=["session:RTH"],
        global_weights={"OB": 0.5, "FVG": 0.5, "BOS": 0.5, "SWEEP": 0.5},
        bucket_stats={},
        min_bucket_events=30,
    )
    control, treatment = rescore_pair(
        ledger,
        global_weights={"OB": 0.5, "FVG": 0.5, "BOS": 0.5, "SWEEP": 0.5},
        contextual_cal=ctx,
        force_global=True,
    )
    for c, t in zip(control.events, treatment.events, strict=False):
        assert c.predicted_prob == pytest.approx(t.predicted_prob)
