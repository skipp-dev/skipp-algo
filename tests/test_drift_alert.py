"""Tests for ``scripts/drift_alert.py`` (Sprint C9)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.drift_alert import (
    brown_forsythe_two_sample,
    compute_drift_report,
    ks_two_sample,
    population_stability_index,
    psi_severity,
    rolling_drift_score,
    welch_t_two_sample,
)

# ---------------------------------------------------------------------------
# KS two-sample
# ---------------------------------------------------------------------------


def test_ks_identical_samples_zero_statistic() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    stat, p = ks_two_sample(a, a)
    assert stat == 0.0
    assert p is not None and p == pytest.approx(1.0)


def test_ks_disjoint_samples_statistic_one() -> None:
    a = np.linspace(0, 1, 50)
    b = np.linspace(2, 3, 50)
    stat, p = ks_two_sample(a, b)
    assert stat == 1.0
    assert p is not None and p < 0.001


def test_ks_returns_none_p_for_empty_input() -> None:
    stat, p = ks_two_sample([], [1.0, 2.0])
    assert stat == 0.0
    assert p is None


def test_ks_p_value_tracks_drift_severity() -> None:
    """As live samples shift further from baseline, p shrinks."""

    rng = np.random.default_rng(42)
    baseline = rng.normal(0.0, 1.0, size=500)
    p_small = ks_two_sample(baseline, rng.normal(0.05, 1.0, size=500))[1]
    p_large = ks_two_sample(baseline, rng.normal(1.0, 1.0, size=500))[1]
    assert p_small is not None and p_large is not None
    assert p_large < p_small


def test_ks_against_scipy_reference_values() -> None:
    """Hand-checked statistic on a small dataset."""

    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([3.0, 4.0, 5.0, 6.0])
    stat, _p = ks_two_sample(a, b)
    # CDFs at unique points {1,2,3,4,5,6}:
    #   F_a = [0.25, 0.5, 0.75, 1.0, 1.0, 1.0]
    #   F_b = [0,    0,   0.25, 0.5, 0.75, 1.0]
    # |diff|  = [0.25, 0.5, 0.5, 0.5, 0.25, 0.0] → max = 0.5
    assert stat == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# PSI
# ---------------------------------------------------------------------------


def test_psi_identical_distributions_near_zero() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(0.0, 1.0, size=1000)
    psi = population_stability_index(a, a, n_buckets=10)
    assert psi is not None
    assert psi < 0.001


def test_psi_increases_with_distribution_shift() -> None:
    rng = np.random.default_rng(0)
    baseline = rng.normal(0.0, 1.0, size=1000)
    psi_small = population_stability_index(baseline, rng.normal(0.05, 1.0, size=1000))
    psi_large = population_stability_index(baseline, rng.normal(1.0, 1.0, size=1000))
    assert psi_small is not None and psi_large is not None
    assert psi_large > psi_small


def test_psi_returns_none_on_empty_or_degenerate() -> None:
    assert population_stability_index([], [1.0, 2.0]) is None
    assert population_stability_index([1.0, 2.0], []) is None
    # All-equal baseline → degenerate.
    assert population_stability_index([5.0] * 100, [1.0, 2.0, 3.0]) is None


def test_psi_n_buckets_validation() -> None:
    with pytest.raises(ValueError, match="n_buckets"):
        population_stability_index([1.0, 2.0], [1.0, 2.0], n_buckets=1)


def test_psi_severity_thresholds() -> None:
    assert psi_severity(0.05) == "green"
    assert psi_severity(0.099) == "green"
    assert psi_severity(0.10) == "yellow"
    assert psi_severity(0.20) == "yellow"
    assert psi_severity(0.249) == "yellow"
    assert psi_severity(0.25) == "red"
    assert psi_severity(1.0) == "red"


# ---------------------------------------------------------------------------
# Rolling drift score
# ---------------------------------------------------------------------------


def test_rolling_drift_score_zero_when_chunk_matches_baseline() -> None:
    series = [1.0] * 30
    out = rolling_drift_score(series, baseline_mean=1.0, baseline_std=0.5, window=10)
    assert len(out) == 21
    assert all(z == 0.0 for z in out)


def test_rolling_drift_score_grows_with_distance() -> None:
    series = [3.0] * 20
    out = rolling_drift_score(series, baseline_mean=1.0, baseline_std=1.0, window=10)
    # Each window's mean is 3.0 → |z| = 2.0.
    assert all(math.isclose(z, 2.0) for z in out)


def test_rolling_drift_score_skips_when_too_short() -> None:
    out = rolling_drift_score([1.0, 2.0, 3.0], baseline_mean=0, baseline_std=1, window=5)
    assert out == []


def test_rolling_drift_score_validation() -> None:
    with pytest.raises(ValueError, match="baseline_std"):
        rolling_drift_score([1.0, 2.0], baseline_mean=0, baseline_std=0.0, window=2)
    with pytest.raises(ValueError, match="window"):
        rolling_drift_score([1.0, 2.0], baseline_mean=0, baseline_std=1, window=0)


# ---------------------------------------------------------------------------
# compute_drift_report
# ---------------------------------------------------------------------------


def test_drift_report_aggregate_green_when_all_metrics_match() -> None:
    rng = np.random.default_rng(0)
    metrics = {
        "sharpe": (rng.normal(1.0, 0.1, 200), rng.normal(1.0, 0.1, 200)),
        "win_rate": (rng.normal(0.55, 0.05, 200), rng.normal(0.55, 0.05, 200)),
    }
    # Use legacy K-S-only mode for an exact-match assertion; the consensus
    # mode allows occasional single-detector noise on iid samples.
    rep = compute_drift_report(metrics, enable_consensus=False)
    assert rep["aggregate_severity"] == "green"
    assert rep["n_metrics"] == 2
    assert all(f["severity"] == "green" for f in rep["findings"])


def test_drift_report_consensus_default_no_red_on_iid_samples() -> None:
    """Consensus default must not flip aggregate to red on iid samples."""
    rng = np.random.default_rng(0)
    metrics = {
        "sharpe": (rng.normal(1.0, 0.1, 400), rng.normal(1.0, 0.1, 400)),
    }
    rep = compute_drift_report(metrics)
    assert rep["aggregate_severity"] in ("green", "yellow")
    assert rep["enable_consensus"] is True
    assert rep["consensus_min"] == 2


def test_drift_report_consensus_red_when_2_plus_detectors_fire() -> None:
    """2σ mean-shift on equal-variance samples: KS + mean-shift fire → red."""
    rng = np.random.default_rng(7)
    baseline = rng.normal(0.0, 1.0, 400)
    live = rng.normal(2.0, 1.0, 400)
    rep = compute_drift_report({"pnl": (baseline, live)})
    assert rep["aggregate_severity"] == "red"
    finding = rep["findings"][0]
    assert finding["consensus_fires"] >= 2
    assert finding["detectors"]["ks"] in ("red", "yellow")
    assert finding["detectors"]["mean_shift"] in ("red", "yellow")


def test_drift_report_aggregate_red_when_any_metric_is_red() -> None:
    rng = np.random.default_rng(0)
    metrics = {
        "ok": (rng.normal(0, 1, 200), rng.normal(0, 1, 200)),
        "broken": (rng.normal(0, 1, 200), rng.normal(2, 1, 200)),
    }
    rep = compute_drift_report(metrics)
    assert rep["aggregate_severity"] == "red"
    severities = {f["metric"]: f["severity"] for f in rep["findings"]}
    assert severities["broken"] == "red"


def test_drift_report_findings_payload_shape() -> None:
    metrics = {
        "x": (np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 3.0])),
    }
    rep = compute_drift_report(metrics)
    f0 = rep["findings"][0]
    required = {"metric", "statistic", "p_value", "severity", "n_baseline", "n_live"}
    assert required <= set(f0), f"missing required keys: {required - set(f0)}"
    # Consensus-mode keys (additive, do not break legacy consumers).
    assert {"psi", "detectors", "consensus_fires"} <= set(f0)
    assert f0["n_baseline"] == 3
    assert f0["n_live"] == 3


# W5-2 (stat-review wave 5): empty metrics dict must yield yellow, not
# vacuous green.
def test_drift_report_empty_metrics_is_yellow() -> None:
    rep = compute_drift_report({})
    assert rep["aggregate_severity"] == "yellow", (
        "empty metrics must not produce a vacuous green pass"
    )
    assert rep["n_metrics"] == 0
    assert rep["findings"] == []


# ---------------------------------------------------------------------------
# Welch t-test (detector 3, C9/T7 issue #298)
# ---------------------------------------------------------------------------


def test_welch_t_identical_samples_p_near_one() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    t, p = welch_t_two_sample(a, a)
    assert t == pytest.approx(0.0)
    assert p is not None and p == pytest.approx(1.0)


def test_welch_t_large_shift_small_p() -> None:
    rng = np.random.default_rng(3)
    a = rng.normal(0.0, 1.0, 100)
    b = rng.normal(2.0, 1.0, 100)
    t, p = welch_t_two_sample(a, b)
    assert t > 5.0  # live mean above baseline mean → positive t
    assert p is not None and p < 1e-6


def test_welch_t_matches_textbook_value() -> None:
    """Cross-checked against scipy.stats.ttest_ind(equal_var=False)."""
    a = [3.0, 4.0, 5.0, 6.0, 7.0]
    b = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    t, p = welch_t_two_sample(a, b)
    assert t == pytest.approx(2.4019, abs=1e-4)
    assert p is not None and p == pytest.approx(0.0398, abs=1e-3)


def test_welch_t_unequal_variances_use_satterthwaite_df() -> None:
    """Variance imbalance must not blow up the p-value (Welch vs pooled)."""
    rng = np.random.default_rng(5)
    a = rng.normal(0.0, 0.1, 50)
    b = rng.normal(0.0, 3.0, 50)
    _t, p = welch_t_two_sample(a, b)
    assert p is not None and 0.0 < p <= 1.0


@pytest.mark.parametrize(
    "a,b",
    [
        ([1.0], [2.0, 3.0]),  # n_a < 2
        ([1.0, 2.0], [3.0]),  # n_b < 2
        ([1.0, 1.0], [1.0, 1.0]),  # both constant → zero pooled SE
    ],
)
def test_welch_t_degenerate_inputs_return_none(a: list[float], b: list[float]) -> None:
    _t, p = welch_t_two_sample(a, b)
    assert p is None


# ---------------------------------------------------------------------------
# Brown-Forsythe (detector 4, C9/T7 issue #298)
# ---------------------------------------------------------------------------


def test_brown_forsythe_equal_scale_high_p() -> None:
    rng = np.random.default_rng(11)
    a = rng.normal(0.0, 1.0, 200)
    b = rng.normal(0.0, 1.0, 200)
    _f, p = brown_forsythe_two_sample(a, b)
    assert p is not None and p > 0.05


def test_brown_forsythe_doubled_scale_small_p() -> None:
    rng = np.random.default_rng(13)
    a = rng.normal(0.0, 1.0, 200)
    b = rng.normal(0.0, 2.5, 200)
    f, p = brown_forsythe_two_sample(a, b)
    assert f > 10.0
    assert p is not None and p < 1e-4


def test_brown_forsythe_mean_shift_alone_does_not_fire() -> None:
    """Median centering: a pure location shift is NOT a scale change."""
    rng = np.random.default_rng(17)
    a = rng.normal(0.0, 1.0, 200)
    b = rng.normal(5.0, 1.0, 200)
    _f, p = brown_forsythe_two_sample(a, b)
    assert p is not None and p > 0.05


def test_brown_forsythe_robust_to_heavy_tails() -> None:
    """t(df=4) samples with equal scale must not produce a spurious fire
    (the plain F-ratio test fails this — the reason BF was chosen)."""
    rng = np.random.default_rng(19)
    a = rng.standard_t(df=4, size=300)
    b = rng.standard_t(df=4, size=300)
    _f, p = brown_forsythe_two_sample(a, b)
    assert p is not None and p > 0.01


@pytest.mark.parametrize(
    "a,b",
    [
        ([1.0], [2.0, 3.0]),  # n_a < 2
        ([1.0, 2.0], [3.0]),  # n_b < 2
        ([1.0, 1.0, 1.0], [2.0, 2.0, 2.0]),  # both constant → zero within-SS
    ],
)
def test_brown_forsythe_degenerate_inputs_return_none(
    a: list[float], b: list[float]
) -> None:
    _f, p = brown_forsythe_two_sample(a, b)
    assert p is None


def test_brown_forsythe_matches_scipy_reference_value() -> None:
    """Fixed-vector cross-check against scipy.stats.levene(center='median')."""
    a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    b = [1.0, 5.0, 2.0, 9.0, -3.0, 12.0, -6.0, 15.0]
    f, p = brown_forsythe_two_sample(a, b)
    assert f == pytest.approx(7.5162, abs=1e-3)
    assert p is not None and p == pytest.approx(0.0159, abs=1e-3)
