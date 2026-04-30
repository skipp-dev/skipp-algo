"""Tests for scripts/generate_performance_report.py."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from scripts.generate_performance_report import (
    _aggregate,
    _grade,
    _load_pair,
    build_digest,
    load_benchmark,
    render_report,
)

# ── Grade helper ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value, expected",
    [
        (0.10, "A"),
        (0.15, "A"),
        (0.20, "B"),
        (0.30, "C"),
        (0.50, "D"),
        (0.70, "F"),
        (float("nan"), "–"),
    ],
)
def test_grade(value: float, expected: str) -> None:
    assert _grade(value) == expected


# ── Pair loading ─────────────────────────────────────────────────────────────

def _minimal_summary(*, symbol: str = "TEST", timeframe: str = "5m", n_events: int = 10) -> dict:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "scoring": {
            "n_events": n_events,
            "brier_score": 0.25,
            "log_score": 0.70,
            "hit_rate": 0.65,
            "families_present": ["BOS"],
            "family_metrics": {"BOS": {"n_events": 10, "brier_score": 0.25, "hit_rate": 0.65}},
            "calibration": {
                "method": "platt_scaling",
                "calibrated_brier_score": 0.18,
                "calibrated_ece": 0.12,
                "raw_ece": 0.20,
            },
            "stratified_calibration_summary": {"dimensions_present": ["session"]},
            "contextual_calibration_summary": {
                "dimensions_present": ["session"],
                "best_dimension_by_adjusted_brier": "session",
                "best_dimension_by_adjusted_ece": "session",
            },
        },
        "ensemble_quality": {"score": 75.0, "tier": "high"},
        "stratification_coverage": {"dimensions_present": ["session"], "populated_bucket_count": 3},
        "warnings": [],
    }


def test_load_pair_extracts_fields() -> None:
    p = _load_pair(_minimal_summary())
    assert p.symbol == "TEST"
    assert p.n_events == 10
    assert p.calibrated_brier == 0.18
    assert p.ensemble_tier == "high"


def test_load_pair_handles_missing_ensemble() -> None:
    summary = _minimal_summary()
    del summary["ensemble_quality"]
    p = _load_pair(summary)
    assert math.isnan(p.ensemble_score)
    assert p.ensemble_tier == "–"


# ── Aggregation ──────────────────────────────────────────────────────────────

def test_aggregate_computes_weighted_means() -> None:
    pairs = [_load_pair(_minimal_summary(n_events=20)), _load_pair(_minimal_summary(n_events=10))]
    agg = _aggregate(pairs)
    assert agg.total_events == 30
    assert agg.pair_count == 2
    assert agg.symbol_count == 1
    assert abs(agg.avg_brier - 0.25) < 0.01


def test_aggregate_passes_gates_for_good_data() -> None:
    pairs = [_load_pair(_minimal_summary())]
    agg = _aggregate(pairs)
    assert agg.brier_gate == "✅"
    assert agg.ece_gate == "✅"


# ── Markdown rendering ──────────────────────────────────────────────────────

def test_render_report_has_all_sections() -> None:
    pairs = [_load_pair(_minimal_summary())]
    report = render_report(pairs, generated_at="2026-01-01 00:00:00 UTC")
    assert "# SMC Performance Report" in report
    assert "## Headline" in report
    assert "## Per-Symbol × Timeframe Breakdown" in report
    assert "## Per-Family Breakdown" in report
    assert "## Stratification Coverage" in report
    assert "## Warnings" in report


# ── JSON digest ──────────────────────────────────────────────────────────────

def test_digest_contains_headline_and_pairs() -> None:
    pairs = [_load_pair(_minimal_summary())]
    digest = build_digest(pairs, generated_at="2026-01-01")
    assert "headline" in digest
    assert "pairs" in digest
    assert len(digest["pairs"]) == 1
    assert digest["headline"]["total_events"] == 10
    assert digest["headline"]["brier_gate_passed"] is True


# ── Integration with real artifacts ──────────────────────────────────────────

def test_load_benchmark_from_existing_artifacts() -> None:
    """Smoke test against the actual benchmark artifacts."""
    input_dir = Path(__file__).resolve().parents[1] / "artifacts" / "ci" / "measurement_benchmark"
    if not (input_dir / "benchmark_run_manifest.json").exists():
        pytest.skip("No benchmark artifacts present")
    pairs = load_benchmark(input_dir)
    assert len(pairs) >= 6  # at least 6 symbol×timeframe pairs
    assert all(p.n_events > 0 for p in pairs)
