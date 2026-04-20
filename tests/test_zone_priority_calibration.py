"""Tests for zone priority calibration pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.smc_zone_priority_calibration import (
    CalibrationResult,
    ContextualCalibrationResult,
    FamilyStats,
    calibrate_contextual_weights,
    calibrate_from_benchmark,
    calibrate_weights,
    check_contextual_promotion,
    check_drift,
    contextual_to_json,
    load_family_metrics,
    load_stratified_family_metrics,
    render_calibration_report,
    resolve_contextual_weight,
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
    # Prior=0.82, Observed=0.80, Blended = 0.7*0.80 + 0.3*0.82 = 0.806
    assert abs(cal["OB"] - 0.806) < 0.001


def test_calibrate_weights_uses_prior_for_small_n() -> None:
    stats = {"OB": FamilyStats(family="OB", total_events=3, total_hits=3)}
    stats["OB"].hit_rates = [1.0]
    stats["OB"].weights = [3]

    cal = calibrate_weights(stats, smoothing=0.3)
    # n < 5 → falls back to prior
    assert cal["OB"] == 0.82


def test_calibrate_weights_all_defaults_when_empty() -> None:
    cal = calibrate_weights({})
    assert cal["OB"] == 0.82
    assert cal["FVG"] == 0.61
    assert cal["BOS"] == 0.81
    assert cal["SWEEP"] == 0.73


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
    # OB should be pulled up from 0.82 toward 0.90
    assert cal.family_weights["OB"] > 0.82


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


# ── Drift check ──────────────────────────────────────────────────


def test_check_drift_no_violations() -> None:
    cal = CalibrationResult(
        family_weights={"OB": 0.85, "FVG": 0.60, "BOS": 0.78, "SWEEP": 0.70},
        rank_thresholds={"A": 75, "B": 50, "C": 25},
        family_stats={},
        total_events=100,
        total_pairs=4,
        source_dir="/tmp",
    )
    violations = check_drift(cal, max_drift=0.15)
    assert violations == []


def test_check_drift_catches_large_drift() -> None:
    cal = CalibrationResult(
        family_weights={"OB": 0.82, "FVG": 0.61, "BOS": 0.99, "SWEEP": 0.73},
        rank_thresholds={"A": 75, "B": 50, "C": 25},
        family_stats={},
        total_events=100,
        total_pairs=4,
        source_dir="/tmp",
    )
    # BOS: |0.99 - 0.81| = 0.18 > 0.15
    violations = check_drift(cal, max_drift=0.15)
    assert len(violations) == 1
    assert "BOS" in violations[0]
    assert "0.1800" in violations[0]


def test_check_drift_multiple_violations() -> None:
    cal = CalibrationResult(
        family_weights={"OB": 0.99, "FVG": 0.20, "BOS": 0.81, "SWEEP": 0.73},
        rank_thresholds={"A": 75, "B": 50, "C": 25},
        family_stats={},
        total_events=100,
        total_pairs=4,
        source_dir="/tmp",
    )
    # OB: |0.99 - 0.82| = 0.17; FVG: |0.20 - 0.61| = 0.41
    violations = check_drift(cal, max_drift=0.15)
    assert len(violations) == 2
    families = [v.split(":")[0] for v in violations]
    assert "OB" in families
    assert "FVG" in families


def test_check_drift_cli_exits_on_violation(tmp_path: Path) -> None:
    from scripts.smc_zone_priority_calibration import main

    # Create benchmark data with extreme hit rates to cause drift
    _write_scoring(tmp_path, "AAPL", "15m", _make_scoring("AAPL", "15m", {
        "OB": {"n_events": 50, "hit_rate": 0.99},  # prior=0.82 → drift with smoothing=0
        "FVG": {"n_events": 50, "hit_rate": 0.65},
        "BOS": {"n_events": 50, "hit_rate": 0.58},
        "SWEEP": {"n_events": 50, "hit_rate": 0.50},
    }))

    out = tmp_path / "out.json"
    with pytest.raises(SystemExit, match="1"):
        main([
            "--benchmark-dir", str(tmp_path),
            "--output-path", str(out),
            "--smoothing", "0.0",        # pure data, no prior blend
            "--check-drift", "0.15",
        ])


def test_check_drift_cli_passes_within_threshold(tmp_path: Path) -> None:
    from scripts.smc_zone_priority_calibration import main

    # Moderate hit rates — within drift threshold with smoothing
    _write_scoring(tmp_path, "AAPL", "15m", _make_scoring("AAPL", "15m", {
        "OB": {"n_events": 20, "hit_rate": 0.80},
        "FVG": {"n_events": 20, "hit_rate": 0.60},
        "BOS": {"n_events": 20, "hit_rate": 0.65},
        "SWEEP": {"n_events": 20, "hit_rate": 0.55},
    }))

    out = tmp_path / "out.json"
    # Should NOT raise
    main([
        "--benchmark-dir", str(tmp_path),
        "--output-path", str(out),
        "--check-drift", "0.15",
    ])


# ── Benchmark fixture helpers ────────────────────────────────────


def _make_benchmark(
    symbol: str,
    tf: str,
    kpis: list[dict[str, Any]],
    stratified: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "symbol": symbol,
        "timeframe": tf,
        "generated_at": 0.0,
        "kpis": kpis,
        "stratified": stratified or {},
    }


def _write_benchmark(base: Path, symbol: str, tf: str, data: dict) -> None:
    d = base / symbol / tf
    d.mkdir(parents=True, exist_ok=True)
    (d / f"benchmark_{symbol}_{tf}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _kpi(family: str, n: int, hr: float) -> dict[str, Any]:
    return {"family": family, "n_events": n, "hit_rate": hr}


# ── Phase F: load_stratified_family_metrics ──────────────────────


def test_load_stratified_aggregates_across_files(tmp_path: Path) -> None:
    _write_benchmark(tmp_path, "AAPL", "15m", _make_benchmark("AAPL", "15m", [], {
        "session:RTH": [_kpi("OB", 20, 0.90), _kpi("FVG", 15, 0.60)],
        "vol_regime:HIGH_VOL": [_kpi("OB", 10, 0.80)],
    }))
    _write_benchmark(tmp_path, "MSFT", "15m", _make_benchmark("MSFT", "15m", [], {
        "session:RTH": [_kpi("OB", 10, 0.70), _kpi("FVG", 20, 0.50)],
    }))

    buckets = load_stratified_family_metrics(tmp_path)
    assert "session:RTH" in buckets
    rth = buckets["session:RTH"]
    # OB: 20 + 10 = 30 events
    assert rth.family_stats["OB"].total_events == 30
    assert rth.family_stats["OB"].pair_count == 2
    # FVG: 15 + 20 = 35 events
    assert rth.family_stats["FVG"].total_events == 35


def test_load_stratified_skips_empty_buckets(tmp_path: Path) -> None:
    _write_benchmark(tmp_path, "AAPL", "15m", _make_benchmark("AAPL", "15m", [], {
        "session:RTH": [_kpi("OB", 0, 0.0)],
    }))
    buckets = load_stratified_family_metrics(tmp_path)
    # n_events=0 → family should be absent from bucket (or bucket itself absent)
    if "session:RTH" in buckets:
        assert "OB" not in buckets["session:RTH"].family_stats


# ── Phase F: calibrate_contextual_weights ────────────────────────


def _build_bucket_stats(
    context_key: str,
    families: dict[str, tuple[int, float]],
) -> dict:
    """Helper to build ContextBucketStats-compatible data."""
    from scripts.smc_zone_priority_calibration import ContextBucketStats
    cbs = ContextBucketStats(context_key=context_key)
    for fam, (n, hr) in families.items():
        s = FamilyStats(family=fam)
        s.total_events = n
        s.total_hits = round(hr * n)
        s.hit_rates = [hr]
        s.weights = [n]
        cbs.family_stats[fam] = s
    return cbs


def test_contextual_calibration_promotes_sufficient_buckets() -> None:
    buckets = {
        "session:RTH": _build_bucket_stats("session:RTH", {
            "OB": (50, 0.90),  # enough events + high HR → promoted
            "FVG": (50, 0.40),
            "BOS": (50, 0.85),
            "SWEEP": (50, 0.75),
        }),
    }
    global_w = {"OB": 0.82, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73}

    ctx = calibrate_contextual_weights(buckets, global_w, min_events=30)
    assert "session:RTH" in ctx.promoted_buckets
    # OB observed 0.90, blended with 0.82 prior at 30% smoothing → 0.876
    ob_w = ctx.contextual_weights["session"]["RTH"]["OB"]
    assert abs(ob_w - 0.876) < 0.01


def test_contextual_calibration_fallback_below_threshold() -> None:
    buckets = {
        "session:ETH": _build_bucket_stats("session:ETH", {
            "OB": (5, 0.80),  # too few events → NOT promoted
            "FVG": (5, 0.60),
            "BOS": (5, 0.90),
            "SWEEP": (5, 0.70),
        }),
    }
    global_w = {"OB": 0.85, "FVG": 0.60, "BOS": 0.82, "SWEEP": 0.75}

    ctx = calibrate_contextual_weights(buckets, global_w, min_events=30)
    # No family has 30 events → not promoted
    assert "session:ETH" not in ctx.promoted_buckets
    # Weights should fall back to global
    assert ctx.contextual_weights["session"]["ETH"]["OB"] == 0.85


def test_contextual_calibration_json_roundtrip() -> None:
    ctx = ContextualCalibrationResult(
        contextual_weights={"session": {"RTH": {"OB": 0.87, "FVG": 0.52, "BOS": 0.85, "SWEEP": 0.74}}},
        promoted_buckets=["session:RTH"],
        global_weights={"OB": 0.82, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73},
        bucket_stats={},
        min_bucket_events=30,
    )
    d = contextual_to_json(ctx)
    assert isinstance(d, dict)
    assert "contextual_weights" in d
    assert "promoted_buckets" in d
    json.dumps(d)  # must be serializable


# ── Phase F: check_contextual_promotion ──────────────────────────


def test_check_promotion_reports_significant_deltas() -> None:
    ctx = ContextualCalibrationResult(
        contextual_weights={"session": {"RTH": {"OB": 0.92, "FVG": 0.50, "BOS": 0.81, "SWEEP": 0.73}}},
        promoted_buckets=["session:RTH"],
        global_weights={"OB": 0.82, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73},
        bucket_stats={},
        min_bucket_events=30,
    )
    summaries = check_contextual_promotion(ctx, brier_improvement_threshold=0.05)
    assert len(summaries) == 1
    assert "OB" in summaries[0]  # OB +0.10 > threshold
    assert "FVG" in summaries[0]  # FVG -0.11 > threshold


def test_check_promotion_empty_when_no_divergence() -> None:
    ctx = ContextualCalibrationResult(
        contextual_weights={"session": {"RTH": {"OB": 0.83, "FVG": 0.62, "BOS": 0.82, "SWEEP": 0.74}}},
        promoted_buckets=["session:RTH"],
        global_weights={"OB": 0.82, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73},
        bucket_stats={},
        min_bucket_events=30,
    )
    # All deltas < 0.05
    summaries = check_contextual_promotion(ctx, brier_improvement_threshold=0.05)
    assert summaries == []


# ── Phase F: resolve_contextual_weight ───────────────────────────


def test_resolve_uses_session_context_when_promoted() -> None:
    ctx = ContextualCalibrationResult(
        contextual_weights={"session": {"RTH": {"OB": 0.92, "FVG": 0.50, "BOS": 0.85, "SWEEP": 0.73}}},
        promoted_buckets=["session:RTH"],
        global_weights={"OB": 0.82, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73},
        bucket_stats={},
        min_bucket_events=30,
    )
    # Session-promoted → use contextual weight
    assert resolve_contextual_weight(ctx, "OB", session_context="RTH") == 0.92
    assert resolve_contextual_weight(ctx, "FVG", session_context="RTH") == 0.50


def test_resolve_falls_back_to_global_when_not_promoted() -> None:
    ctx = ContextualCalibrationResult(
        contextual_weights={"session": {"ETH": {"OB": 0.82, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73}}},
        promoted_buckets=[],  # nothing promoted
        global_weights={"OB": 0.85, "FVG": 0.60, "BOS": 0.82, "SWEEP": 0.75},
        bucket_stats={},
        min_bucket_events=30,
    )
    assert resolve_contextual_weight(ctx, "OB", session_context="ETH") == 0.85  # global fallback


def test_resolve_uses_vol_regime_when_session_not_available() -> None:
    ctx = ContextualCalibrationResult(
        contextual_weights={
            "vol_regime": {"HIGH_VOL": {"OB": 0.78, "FVG": 0.65, "BOS": 0.81, "SWEEP": 0.80}},
        },
        promoted_buckets=["vol_regime:HIGH_VOL"],
        global_weights={"OB": 0.82, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73},
        bucket_stats={},
        min_bucket_events=30,
    )
    # No session → falls through to vol_regime
    assert resolve_contextual_weight(ctx, "FVG", vol_regime="HIGH_VOL") == 0.65


def test_resolve_none_contextual_returns_default() -> None:
    w = resolve_contextual_weight(None, "OB")
    assert w == 0.82  # hand-tuned default


# ── Phase F: build_zone_priority with contextual_calibration ─────


def test_build_zone_priority_with_contextual_calibration() -> None:
    from scripts.smc_zone_priority import build_zone_priority

    ctx = ContextualCalibrationResult(
        contextual_weights={
            "session": {"RTH": {"OB": 0.40, "FVG": 0.95, "BOS": 0.40, "SWEEP": 0.40}},
        },
        promoted_buckets=["session:RTH"],
        global_weights={"OB": 0.82, "FVG": 0.61, "BOS": 0.81, "SWEEP": 0.73},
        bucket_stats={},
        min_bucket_events=30,
    )
    result = build_zone_priority(
        regime="NEUTRAL",
        session_context="RTH",
        vol_regime="NORMAL",
        contextual_calibration=ctx,
    )
    # FVG base = 0.95 (from contextual) → should dominate after additive bonuses
    assert result["ZONE_PRIORITY_TOP_FAMILY"] == "FVG"


def test_build_zone_priority_contextual_none_backward_compat() -> None:
    from scripts.smc_zone_priority import build_zone_priority

    # contextual_calibration=None should not change behavior
    result = build_zone_priority(regime="RISK_ON", htf_aligned=True, contextual_calibration=None)
    assert result["ZONE_PRIORITY_TOP_FAMILY"] == "OB"
