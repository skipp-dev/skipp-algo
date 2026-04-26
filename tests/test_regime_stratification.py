"""Tests for ``scripts/regime_stratification.py`` (Sprint C5 / T3)."""

from __future__ import annotations

import math

import pytest

from scripts import regime_stratification as rs


def _make_trades(
    *,
    n_per_regime: dict[str, int],
    pnl_per_regime: dict[str, float] | None = None,
    seed: int = 0,
) -> list[dict[str, object]]:
    """Synthetic trade list with per-regime constant PnL (deterministic)."""

    pnl_per_regime = pnl_per_regime or {}
    trades: list[dict[str, object]] = []
    for regime, n in n_per_regime.items():
        base = pnl_per_regime.get(regime, 0.001)
        for i in range(n):
            # Tiny deterministic noise so std is non-zero for Sharpe.
            noise = ((i % 7) - 3) * 1e-4
            trades.append({"regime_at_entry": regime, "pnl": base + noise})
    return trades


# ---------------------------------------------------------------------------
# stratify_trades_by_regime
# ---------------------------------------------------------------------------


def test_stratify_buckets_and_orders_alphabetically_unknown_last() -> None:
    trades = [
        {"regime_at_entry": "RISK_ON", "pnl": 0.01},
        {"regime_at_entry": None, "pnl": -0.01},
        {"regime_at_entry": "RISK_OFF", "pnl": -0.005},
        {"regime_at_entry": "", "pnl": 0.002},
        {"regime_at_entry": "RISK_ON", "pnl": 0.015},
    ]
    out = rs.stratify_trades_by_regime(trades)
    assert list(out) == ["RISK_OFF", "RISK_ON", "UNKNOWN"]
    assert len(out["RISK_ON"]) == 2
    assert len(out["RISK_OFF"]) == 1
    assert len(out["UNKNOWN"]) == 2


def test_stratify_custom_regime_col() -> None:
    trades = [
        {"vol_regime": "EXTREME", "pnl": 0.0},
        {"vol_regime": "NORMAL", "pnl": 0.0},
    ]
    out = rs.stratify_trades_by_regime(trades, regime_col="vol_regime")
    assert set(out) == {"EXTREME", "NORMAL"}


# ---------------------------------------------------------------------------
# unknown_regime_share
# ---------------------------------------------------------------------------


def test_unknown_regime_share_empty_mapping_is_zero() -> None:
    assert rs.unknown_regime_share({}) == 0.0


def test_unknown_regime_share_no_unknown_bucket_is_zero() -> None:
    trades = [
        {"regime_at_entry": "RISK_ON", "pnl": 0.01},
        {"regime_at_entry": "RISK_OFF", "pnl": -0.005},
    ]
    buckets = rs.stratify_trades_by_regime(trades)
    assert "UNKNOWN" not in buckets
    assert rs.unknown_regime_share(buckets) == 0.0


def test_unknown_regime_share_mixed_buckets_returns_correct_fraction() -> None:
    trades = [
        {"regime_at_entry": "RISK_ON", "pnl": 0.01},
        {"regime_at_entry": "RISK_ON", "pnl": 0.02},
        {"regime_at_entry": "RISK_OFF", "pnl": -0.005},
        {"regime_at_entry": None, "pnl": 0.001},
        {"regime_at_entry": "", "pnl": 0.002},
    ]
    buckets = rs.stratify_trades_by_regime(trades)
    # 2 of 5 trades fall into UNKNOWN.
    assert rs.unknown_regime_share(buckets) == pytest.approx(2 / 5)


def test_unknown_regime_share_all_unknown_returns_one() -> None:
    trades = [
        {"regime_at_entry": None, "pnl": 0.001},
        {"regime_at_entry": "", "pnl": 0.002},
    ]
    buckets = rs.stratify_trades_by_regime(trades)
    assert rs.unknown_regime_share(buckets) == 1.0


# ---------------------------------------------------------------------------
# compute_regime_conditional_metrics
# ---------------------------------------------------------------------------


def test_metrics_per_regime_includes_frequency_and_skips_below_floor() -> None:
    trades = _make_trades(n_per_regime={"RISK_ON": 50, "RISK_OFF": 10})
    buckets = rs.stratify_trades_by_regime(trades)
    out = rs.compute_regime_conditional_metrics(buckets)
    assert out["RISK_ON"]["n"] == 50
    assert out["RISK_OFF"]["skipped_reason"] == "insufficient_n"
    assert out["RISK_OFF"]["n"] == 10
    # Frequency reported for both, including skipped.
    assert math.isclose(out["RISK_ON"]["regime_frequency_pct"], 50 / 60)
    assert math.isclose(out["RISK_OFF"]["regime_frequency_pct"], 10 / 60)
    # Sharpe / win-rate populated for the non-skipped regime.
    assert out["RISK_ON"]["sharpe"] is not None
    assert 0.0 <= out["RISK_ON"]["win_rate"] <= 1.0


def test_metrics_max_dd_non_positive() -> None:
    # All-negative regime should produce a strictly negative max_dd.
    trades = _make_trades(
        n_per_regime={"RISK_OFF": 50},
        pnl_per_regime={"RISK_OFF": -0.005},
    )
    buckets = rs.stratify_trades_by_regime(trades)
    metrics = rs.compute_regime_conditional_metrics(buckets)["RISK_OFF"]
    assert metrics["max_dd"] < 0.0


def test_metrics_skipped_regime_below_custom_floor() -> None:
    trades = _make_trades(n_per_regime={"RISK_ON": 5})
    buckets = rs.stratify_trades_by_regime(trades)
    out = rs.compute_regime_conditional_metrics(buckets, min_n_per_regime=10)
    assert out["RISK_ON"]["skipped_reason"] == "insufficient_n"


# ---------------------------------------------------------------------------
# compute_regime_aware_aggregate
# ---------------------------------------------------------------------------


def test_aggregate_frequency_weighted_equal_freq_equals_simple_mean() -> None:
    """Equal regime frequencies → freq-weighted aggregate == arithmetic mean."""

    per_regime = {
        "RISK_ON": {"sharpe": 1.0, "regime_frequency_pct": 0.5, "n": 100},
        "RISK_OFF": {"sharpe": -0.4, "regime_frequency_pct": 0.5, "n": 100},
    }
    out = rs.compute_regime_aware_aggregate(per_regime, metric="sharpe")
    assert math.isclose(out["value"], 0.30)
    assert out["method"] == "frequency_weighted"
    assert out["regimes_used"] == ["RISK_ON", "RISK_OFF"]
    assert out["regimes_skipped"] == []


def test_aggregate_skips_skipped_regimes() -> None:
    per_regime = {
        "RISK_ON": {"sharpe": 1.5, "regime_frequency_pct": 0.7, "n": 100},
        "RISK_OFF": {"skipped_reason": "insufficient_n", "n": 10, "regime_frequency_pct": 0.3},
    }
    out = rs.compute_regime_aware_aggregate(per_regime, metric="sharpe")
    assert math.isclose(out["value"], 1.5)
    assert out["regimes_used"] == ["RISK_ON"]
    assert out["regimes_skipped"] == ["RISK_OFF"]


def test_aggregate_returns_none_when_all_skipped() -> None:
    per_regime = {
        "RISK_ON": {"skipped_reason": "insufficient_n", "n": 5, "regime_frequency_pct": 1.0},
    }
    out = rs.compute_regime_aware_aggregate(per_regime, metric="sharpe")
    assert out["value"] is None
    assert out["regimes_used"] == []


def test_aggregate_equal_weighting_mode() -> None:
    """When freq_weighting=False, all regimes count equally regardless of n."""

    per_regime = {
        "RISK_ON": {"sharpe": 2.0, "regime_frequency_pct": 0.99, "n": 990},
        "RISK_OFF": {"sharpe": 0.0, "regime_frequency_pct": 0.01, "n": 10},
    }
    # With freq weighting the heavily-RISK_ON setup looks ≈ 1.98.
    out_freq = rs.compute_regime_aware_aggregate(per_regime, metric="sharpe")
    assert out_freq["value"] > 1.9
    # Equal weighting collapses to (2 + 0) / 2 = 1.0.
    out_eq = rs.compute_regime_aware_aggregate(
        per_regime, metric="sharpe", freq_weighting=False
    )
    assert math.isclose(out_eq["value"], 1.0)


def test_aggregate_emits_warning_when_unknown_share_exceeds_threshold() -> None:
    """C5 deep-review fix: high unknown-regime share must surface as a warning."""
    per_regime = {
        "RISK_ON": {"sharpe": 1.0, "regime_frequency_pct": 0.5, "n": 100},
        "RISK_OFF": {"sharpe": 0.5, "regime_frequency_pct": 0.5, "n": 100},
    }
    out = rs.compute_regime_aware_aggregate(
        per_regime, metric="sharpe", unknown_share=0.12
    )
    assert "warning" in out, "expected warning when unknown_share > 0.05"
    assert "0.120" in out["warning"]
    assert out["unknown_share"] == 0.12


def test_aggregate_no_warning_when_unknown_share_below_threshold() -> None:
    per_regime = {
        "RISK_ON": {"sharpe": 1.0, "regime_frequency_pct": 1.0, "n": 100},
    }
    out = rs.compute_regime_aware_aggregate(
        per_regime, metric="sharpe", unknown_share=0.02
    )
    assert "warning" not in out
    assert out["unknown_share"] == 0.02


def test_aggregate_unknown_share_kwarg_is_optional() -> None:
    """Backward-compat: callers that omit unknown_share keep working."""
    per_regime = {
        "RISK_ON": {"sharpe": 1.0, "regime_frequency_pct": 1.0, "n": 100},
    }
    out = rs.compute_regime_aware_aggregate(per_regime, metric="sharpe")
    assert out["unknown_share"] is None
    assert "warning" not in out


# ---------------------------------------------------------------------------
# detect_regime_concentration
# ---------------------------------------------------------------------------


def test_concentration_flagged_when_one_regime_dominates() -> None:
    trades_per_regime = {
        "RISK_ON": [{"pnl": 1.0} for _ in range(100)],
        "RISK_OFF": [{"pnl": 0.05} for _ in range(50)],
    }
    out = rs.detect_regime_concentration(trades_per_regime, threshold=0.80)
    assert out["concentrated"] is True
    assert out["dominant_regime"] == "RISK_ON"
    assert out["share_of_total_pnl"] > 0.95


def test_concentration_not_flagged_when_pnl_balanced() -> None:
    trades_per_regime = {
        "RISK_ON": [{"pnl": 1.0} for _ in range(50)],
        "RISK_OFF": [{"pnl": 1.0} for _ in range(50)],
    }
    out = rs.detect_regime_concentration(trades_per_regime, threshold=0.80)
    assert out["concentrated"] is False
    assert math.isclose(out["share_of_total_pnl"], 0.50)


def test_concentration_returns_safe_default_when_no_positive_pnl() -> None:
    trades_per_regime = {
        "RISK_OFF": [{"pnl": -1.0} for _ in range(50)],
    }
    out = rs.detect_regime_concentration(trades_per_regime, threshold=0.80)
    assert out["concentrated"] is False
    assert out["dominant_regime"] is None
    assert out["share_of_total_pnl"] == 0.0


def test_concentration_threshold_validation() -> None:
    with pytest.raises(ValueError, match="threshold must be"):
        rs.detect_regime_concentration({}, threshold=0.0)
    with pytest.raises(ValueError, match="threshold must be"):
        rs.detect_regime_concentration({}, threshold=1.5)


# ---------------------------------------------------------------------------
# Integration: end-to-end stratify → metrics → aggregate
# ---------------------------------------------------------------------------


def test_end_to_end_regime_concentration_invalidates_naive_aggregate() -> None:
    """C5 headline scenario: aggregate Sharpe looks fine; per-regime exposes the bet.

    Build a setup with strong positive PnL in RISK_ON (50% frequency)
    and strong negative PnL in RISK_OFF (50% frequency). Naive
    aggregate Sharpe is roughly zero; concentration detector flags
    the setup as a regime bet.
    """

    trades_on = [{"regime_at_entry": "RISK_ON", "pnl": 0.02 + ((i % 5) - 2) * 1e-4} for i in range(60)]
    trades_off = [{"regime_at_entry": "RISK_OFF", "pnl": -0.018 + ((i % 5) - 2) * 1e-4} for i in range(60)]
    trades = trades_on + trades_off

    buckets = rs.stratify_trades_by_regime(trades)
    metrics = rs.compute_regime_conditional_metrics(buckets)
    assert metrics["RISK_ON"]["sharpe"] is not None and metrics["RISK_ON"]["sharpe"] > 0
    assert metrics["RISK_OFF"]["sharpe"] is not None and metrics["RISK_OFF"]["sharpe"] < 0

    agg = rs.compute_regime_aware_aggregate(metrics, metric="sharpe")
    # Per-regime Sharpes are equal-and-opposite by construction, so the
    # frequency-weighted aggregate must be much smaller in magnitude
    # than either single-regime Sharpe — the C5 headline finding.
    on_sharpe = abs(metrics["RISK_ON"]["sharpe"])
    off_sharpe = abs(metrics["RISK_OFF"]["sharpe"])
    smaller_individual = min(on_sharpe, off_sharpe)
    assert abs(agg["value"]) < smaller_individual

    concentration = rs.detect_regime_concentration(buckets)
    # Total positive PnL all comes from RISK_ON → fully concentrated.
    assert concentration["concentrated"] is True
    assert concentration["dominant_regime"] == "RISK_ON"


# ---------------------------------------------------------------------------
# Negative-case coverage (C-sprint deep-review C5)
# ---------------------------------------------------------------------------


def test_stratify_coerces_dict_regime_label_via_str() -> None:
    """A producer-side bug that emits a dict regime label must not
    crash with an unhashable-key error. The label is coerced via
    ``str()`` so the defect surfaces on the dashboard as a weirdly-
    named bucket instead of silently dropping the trades.
    """
    trades = [{"regime_at_entry": {"phase": "A"}, "pnl": 0.01}]
    buckets = rs.stratify_trades_by_regime(trades)
    assert "{'phase': 'A'}" in buckets
    assert len(buckets["{'phase': 'A'}"]) == 1


def test_metrics_drops_non_finite_pnls_with_recorded_count() -> None:
    """NaN / inf PnLs must NOT silently propagate to a NaN Sharpe or
    a 0.0 max-DD that the dashboard then renders as a healthy regime
    (C-sprint deep-review C5 finding).
    """
    trades = _make_trades(n_per_regime={"R": 30})
    # Inject 5 NaN and 3 inf trades.
    for _ in range(5):
        trades.append({"regime_at_entry": "R", "pnl": float("nan")})
    for _ in range(3):
        trades.append({"regime_at_entry": "R", "pnl": float("inf")})
    buckets = rs.stratify_trades_by_regime(trades)
    metrics = rs.compute_regime_conditional_metrics(buckets, min_n_per_regime=10)
    record = metrics["R"]
    # Sharpe is computed on finite PnLs only.
    assert record["sharpe"] is not None
    assert math.isfinite(record["sharpe"])
    # Drops are surfaced.
    assert record["n_non_finite_dropped"] == 8
    assert record["n"] == 38  # raw count, kept aligned with regime_frequency_pct
    assert record["n_finite"] == 30  # finite count actually fed to the metrics


def test_metrics_skipped_with_insufficient_finite_n_after_drop() -> None:
    """If non-finite drops push the regime below the n-floor, the
    record reports skipped_reason='insufficient_finite_n' (distinct
    from 'insufficient_n') so the operator can tell the difference
    between *not enough trades* and *not enough valid trades*.
    """
    trades = [{"regime_at_entry": "R", "pnl": float("nan")} for _ in range(15)]
    trades += [{"regime_at_entry": "R", "pnl": 0.01} for _ in range(20)]
    buckets = rs.stratify_trades_by_regime(trades)
    metrics = rs.compute_regime_conditional_metrics(buckets, min_n_per_regime=30)
    record = metrics["R"]
    assert record["skipped_reason"] == "insufficient_finite_n"
    assert record["n_finite"] == 20
    assert record["n_non_finite_dropped"] == 15


def test_stratify_preserves_falsy_non_none_labels() -> None:
    """C-sprint deep-review C5 followup (Copilot #306): integer ``0``
    and boolean ``False`` are valid regime IDs and must survive as
    ``"0"``/``"False"`` instead of being collapsed into UNKNOWN."""

    trades = [
        {"regime_at_entry": 0, "pnl": 1.0},
        {"regime_at_entry": False, "pnl": -1.0},
        {"regime_at_entry": None, "pnl": 0.0},
        {"regime_at_entry": "", "pnl": 0.0},
    ]
    buckets = rs.stratify_trades_by_regime(trades)
    assert "0" in buckets
    assert "False" in buckets
    assert buckets["UNKNOWN"]
    assert len(buckets["UNKNOWN"]) == 2  # only None and "" map to UNKNOWN
