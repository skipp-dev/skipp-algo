"""Tests for zone priority calibration pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.smc_zone_priority_calibration import (
    CalibrationResult,
    FamilyStats,
    calibrate_from_benchmark,
    calibrate_weights,
    load_family_metrics,
    render_calibration_report,
    to_json,
)


# ── Fixtures ─────────────────────────────────────────────────────


def _make_scoring(
    symbol: str,
    tf: str,
    family_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "symbol": symbol,
        "timeframe": tf,
        "n_events": sum(fm.get("n_events", 0) for fm in family_metrics.values()),
        "family_metrics": family_metrics,
    }


def _write_scoring(base: Path, symbol: str, tf: str, data: dict) -> None:
    d = base / symbol / tf
    d.mkdir(parents=True, exist_ok=True)
    (d / f"scoring_{symbol}_{tf}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


# ── FamilyStats ──────────────────────────────────────────────────


def test_family_stats_weighted_hit_rate() -> None:
    s = FamilyStats(family="OB")
    s.hit_rates = [0.80, 0.60]
    s.weights = [10, 5]
    # (0.80*10 + 0.60*5) / 15 = 11.0/15 ≈ 0.7333
    assert abs(s.weighted_hit_rate - 0.7333) < 0.01


def test_family_stats_simple_hit_rate() -> None:
    s = FamilyStats(family="OB", total_events=20, total_hits=15)
    assert s.simple_hit_rate == 0.75


def test_family_stats_empty() -> None:
    s = FamilyStats(family="X")
    assert s.weighted_hit_rate == 0.0
    assert s.simple_hit_rate == 0.0


# ── load_family_metrics ──────────────────────────────────────────


def test_load_family_metrics_basic(tmp_path: Path) -> None:
    scoring = _make_scoring("AAPL", "15m", {
        "OB": {"n_events": 10, "hit_rate": 0.80},
        "FVG": {"n_events": 8, "hit_rate": 0.50},
    })
    _write_scoring(tmp_path, "AAPL", "15m", scoring)

    stats = load_family_metrics(tmp_path)
    assert "OB" in stats
    assert stats["OB"].total_events == 10
    assert stats["OB"].simple_hit_rate == 0.80
    assert "FVG" in stats
    assert stats["FVG"].total_events == 8


def test_load_aggregates_across_pairs(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "15m", _make_scoring("AAPL", "15m", {
        "OB": {"n_events": 10, "hit_rate": 1.0},
    }))
    _write_scoring(tmp_path, "MSFT", "15m", _make_scoring("MSFT", "15m", {
        "OB": {"n_events": 10, "hit_rate": 0.50},
    }))

    stats = load_family_metrics(tmp_path)
    ob = stats["OB"]
    assert ob.total_events == 20
    assert ob.pair_count == 2
    # Weighted: (1.0*10 + 0.5*10) / 20 = 0.75
    assert abs(ob.weighted_hit_rate - 0.75) < 0.01


def test_load_skips_empty_family_metrics(tmp_path: Path) -> None:
    data = {"schema_version": "2.0.0", "family_metrics": {}}
    d = tmp_path / "AAPL" / "15m"
    d.mkdir(parents=True)
    (d / "scoring_AAPL_15m.json").write_text(json.dumps(data))
    stats = load_family_metrics(tmp_path)
    assert stats == {}


def test_load_skips_zero_events(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "15m", _make_scoring("AAPL", "15m", {
        "OB": {"n_events": 0, "hit_rate": 0.0},
    }))
    stats = load_family_metrics(tmp_path)
    assert "OB" not in stats


# ── calibrate_weights ────────────────────────────────────────────


def test_calibrate_weights_blends_prior_and_observed() -> None:
    stats = {"OB": FamilyStats(family="OB", total_events=20, total_hits=16)}
    stats["OB"].hit_rates = [0.80]
    stats["OB"].weights = [20]

    cal = calibrate_weights(stats, smoothing=0.3)
    # Prior=0.72, Observed=0.80, Blended = 0.7*0.80 + 0.3*0.72 = 0.776
    assert abs(cal["OB"] - 0.776) < 0.001


def test_calibrate_weights_uses_prior_for_small_n() -> None:
    stats = {"OB": FamilyStats(family="OB", total_events=3, total_hits=3)}
    stats["OB"].hit_rates = [1.0]
    stats["OB"].weights = [3]

    cal = calibrate_weights(stats, smoothing=0.3)
    # n < 5 → falls back to prior
    assert cal["OB"] == 0.72


def test_calibrate_weights_all_defaults_when_empty() -> None:
    cal = calibrate_weights({})
    assert cal["OB"] == 0.72
    assert cal["FVG"] == 0.65
    assert cal["BOS"] == 0.58
    assert cal["SWEEP"] == 0.50


def test_calibrate_weights_clamped() -> None:
    stats = {"OB": FamilyStats(family="OB", total_events=100, total_hits=100)}
    stats["OB"].hit_rates = [1.0]
    stats["OB"].weights = [100]

    cal = calibrate_weights(stats, smoothing=0.0)
    assert cal["OB"] <= 1.0


# ── calibrate_from_benchmark (integration) ───────────────────────


def test_calibrate_from_benchmark(tmp_path: Path) -> None:
    for sym in ("AAPL", "MSFT"):
        _write_scoring(tmp_path, sym, "15m", _make_scoring(sym, "15m", {
            "OB": {"n_events": 10, "hit_rate": 0.90},
            "FVG": {"n_events": 8, "hit_rate": 0.50},
            "BOS": {"n_events": 6, "hit_rate": 0.67},
            "SWEEP": {"n_events": 5, "hit_rate": 0.40},
        }))

    cal = calibrate_from_benchmark(tmp_path, smoothing=0.3)
    assert cal.total_events > 0
    assert cal.total_pairs > 0
    assert set(cal.family_weights.keys()) == {"OB", "FVG", "BOS", "SWEEP"}
    # OB should be pulled up from 0.72 toward 0.90
    assert cal.family_weights["OB"] > 0.72


def test_calibrate_with_real_artifacts() -> None:
    benchmark_dir = Path("artifacts/ci/measurement_benchmark")
    if not benchmark_dir.exists():
        pytest.skip("No benchmark artifacts present")

    cal = calibrate_from_benchmark(benchmark_dir)
    assert cal.total_events > 0
    assert all(0 <= w <= 1 for w in cal.family_weights.values())


# ── Rendering ────────────────────────────────────────────────────


def test_render_report_has_all_sections(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "15m", _make_scoring("AAPL", "15m", {
        "OB": {"n_events": 10, "hit_rate": 0.80},
        "FVG": {"n_events": 8, "hit_rate": 0.50},
        "BOS": {"n_events": 6, "hit_rate": 0.67},
        "SWEEP": {"n_events": 5, "hit_rate": 0.40},
    }))

    cal = calibrate_from_benchmark(tmp_path)
    md = render_calibration_report(cal)
    assert "# Zone Priority Calibration Report" in md
    assert "Family Weights" in md
    assert "Per-Family Detail" in md
    assert "Rank Thresholds" in md
    assert "OB" in md


def test_to_json_roundtrip(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "15m", _make_scoring("AAPL", "15m", {
        "OB": {"n_events": 10, "hit_rate": 0.80},
    }))
    cal = calibrate_from_benchmark(tmp_path)
    d = to_json(cal)
    assert isinstance(d, dict)
    assert "family_weights" in d
    assert "family_stats" in d
    # Ensure JSON serializable
    json.dumps(d)


# ── Wire into build_zone_priority ────────────────────────────────


def test_build_zone_priority_accepts_calibrated_weights() -> None:
    from scripts.smc_zone_priority import build_zone_priority

    # With calibrated weights heavily favoring SWEEP
    custom = {"OB": 0.30, "FVG": 0.30, "BOS": 0.30, "SWEEP": 0.99}
    result = build_zone_priority(
        regime="NEUTRAL",
        vol_regime="EXTREME",
        calibrated_family_weights=custom,
    )
    # SWEEP should be selected as top family (0.99 base + 0.15 extreme bonus)
    assert result["ZONE_PRIORITY_TOP_FAMILY"] == "SWEEP"


def test_build_zone_priority_default_weights_unchanged() -> None:
    from scripts.smc_zone_priority import build_zone_priority

    # Without calibrated weights, default behavior preserved
    result = build_zone_priority(regime="RISK_ON", htf_aligned=True)
    # OB should be top family in default mode with RISK_ON + HTF aligned
    assert result["ZONE_PRIORITY_TOP_FAMILY"] == "OB"
