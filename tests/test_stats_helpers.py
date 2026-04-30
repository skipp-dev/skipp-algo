"""Tests for ``open_prep.stats_helpers`` (Sprint C6 / T2-T4).

Coverage:
- ``compute_skew_kurtosis`` Gaussian sanity, lognormal positive skew,
  edge cases.
- ``probabilistic_sharpe`` Bailey-style replication, symmetry, skew
  penalty, edge cases.
- ``min_trl`` Wikipedia-replicated reference values, monotonicity,
  validation.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from open_prep import stats_helpers as sh

# ---------------------------------------------------------------------------
# compute_skew_kurtosis
# ---------------------------------------------------------------------------


def test_skew_kurtosis_gaussian_within_tolerance() -> None:
    rng = np.random.default_rng(20260426)
    samples = rng.normal(0.0, 1.0, size=20_000).tolist()
    skew, kurt = sh.compute_skew_kurtosis(samples)
    assert abs(skew) < 0.10
    assert abs(kurt - 3.0) < 0.15


def test_skew_kurtosis_lognormal_positive_skew() -> None:
    rng = np.random.default_rng(20260427)
    samples = rng.lognormal(mean=0.0, sigma=0.5, size=10_000).tolist()
    skew, kurt = sh.compute_skew_kurtosis(samples)
    assert skew > 0.5
    assert kurt > 3.0


def test_skew_kurtosis_rejects_too_few_observations() -> None:
    with pytest.raises(ValueError, match="at least 30"):
        sh.compute_skew_kurtosis([0.01] * 10)


def test_skew_kurtosis_rejects_constant_returns() -> None:
    with pytest.raises(ValueError, match="variance is zero"):
        sh.compute_skew_kurtosis([0.005] * 50)


# ---------------------------------------------------------------------------
# compute_sharpe
# ---------------------------------------------------------------------------


def test_compute_sharpe_basic_and_annualization() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=500).tolist()
    sr = sh.compute_sharpe(returns)
    sr_ann = sh.compute_sharpe(returns, annualize=True, periods_per_year=252)
    assert abs(sr_ann - sr * math.sqrt(252)) < 1e-9


# ---------------------------------------------------------------------------
# probabilistic_sharpe
# ---------------------------------------------------------------------------


def test_psr_symmetry_at_threshold_equals_observed() -> None:
    rng = np.random.default_rng(20260426)
    returns = rng.normal(0.001, 0.01, size=500).tolist()
    sr_hat = sh.compute_sharpe(returns)
    out = sh.probabilistic_sharpe(returns, sr_star=sr_hat)
    # PSR(SR* = SR_hat) ≡ Φ(0) = 0.5.
    assert abs(out["psr"] - 0.5) < 1e-12


def test_psr_high_for_strong_gaussian_signal() -> None:
    """Bailey-Lopez de Prado canonical example.

    With SR_hat = 0.95 annualised, n = 750 daily obs, normal returns
    (skew=0, kurt=3), PSR(SR*=0) should be ≈ 0.95 — the Wikipedia /
    QWAFAFEW datapoint. We pass ``sharpe_hat`` explicitly so the test
    is not destabilised by sampling noise around the true Sharpe.
    """

    rng = np.random.default_rng(20260428)
    # Returns vector solely supplies near-Gaussian skew/kurtosis;
    # the SR_hat used in the formula is locked via ``sharpe_hat``.
    returns = rng.normal(0.0, 0.01, size=750).tolist()
    out = sh.probabilistic_sharpe(
        returns,
        sr_star=0.0,
        sharpe_hat=0.95,
        annualize=True,
        periods_per_year=252,
    )
    # Wikipedia / Bailey: ≈ 0.95. Allow ±2pp for finite-sample
    # skew/kurtosis estimator noise on n=750 Gaussian draws.
    assert 0.93 <= out["psr"] <= 0.97


def test_psr_low_when_sharpe_below_threshold() -> None:
    rng = np.random.default_rng(20260429)
    returns = rng.normal(0.0, 0.01, size=500).tolist()
    out = sh.probabilistic_sharpe(returns, sr_star=0.5)
    assert out["psr"] < 0.10


def test_psr_negative_skew_penalty_reduces_psr() -> None:
    """For the same SR_hat, more negative skew → lower PSR.

    Build two return paths with identical mean/std but opposite skew
    by reflecting the same lognormal noise.
    """

    rng = np.random.default_rng(20260430)
    base = rng.lognormal(mean=0.0, sigma=0.4, size=400)
    base_centred = base - base.mean()
    # "right-skewed": returns += tiny positive drift
    returns_pos = (base_centred + 0.005).tolist()
    # "left-skewed": flip sign of the noise
    returns_neg = (-base_centred + 0.005).tolist()

    sr_pos = sh.compute_sharpe(returns_pos)
    sr_neg = sh.compute_sharpe(returns_neg)
    # Means/stds match by construction; both Sharpes should be close.
    assert abs(sr_pos - sr_neg) < 1e-6

    psr_pos = sh.probabilistic_sharpe(returns_pos, sr_star=0.0)
    psr_neg = sh.probabilistic_sharpe(returns_neg, sr_star=0.0)
    # Right-skewed series should get a higher PSR than left-skewed at
    # the same point estimate.
    assert psr_pos["psr"] > psr_neg["psr"]


def test_psr_rejects_too_few_observations() -> None:
    with pytest.raises(ValueError, match="at least 30"):
        sh.probabilistic_sharpe([0.01] * 10, sr_star=0.0)


# ---------------------------------------------------------------------------
# min_trl
# ---------------------------------------------------------------------------


def test_min_trl_wikipedia_reference_sr095_target0() -> None:
    """Wikipedia / Bailey example: SR_hat=0.95 ann, SR*=0, normal → ~3y daily.

    Working at per-period frequency: SR_period = 0.95 / sqrt(252).
    Plug into MinTRL with skew=0, kurt=3, alpha=0.05 — should return
    around 750 (3 years of daily observations).
    """

    sr_period = 0.95 / math.sqrt(252)
    n = sh.min_trl(sr_period, sr_star=0.0, skew=0.0, kurtosis=3.0, alpha=0.05)
    # Expected ~750; allow ±5% per the plan acceptance criterion.
    assert 715 <= n <= 785


def test_min_trl_wikipedia_reference_sr2_target1() -> None:
    """SR_hat=2.0 ann, SR*=1.0, normal → ~690 obs (~2.73y daily)."""

    sr_period_hat = 2.0 / math.sqrt(252)
    sr_period_star = 1.0 / math.sqrt(252)
    n = sh.min_trl(
        sr_period_hat,
        sr_star=sr_period_star,
        skew=0.0,
        kurtosis=3.0,
        alpha=0.05,
    )
    # Expected ~690; ±5%.
    assert 655 <= n <= 725


def test_min_trl_negative_skew_increases_observations() -> None:
    base_n = sh.min_trl(0.06, sr_star=0.0, skew=0.0, kurtosis=3.0, alpha=0.05)
    skewed_n = sh.min_trl(0.06, sr_star=0.0, skew=-0.5, kurtosis=3.0, alpha=0.05)
    assert skewed_n > base_n


def test_min_trl_rejects_sr_at_or_below_target() -> None:
    with pytest.raises(ValueError, match="strictly greater"):
        sh.min_trl(0.0, sr_star=0.0)
    with pytest.raises(ValueError, match="strictly greater"):
        sh.min_trl(0.5, sr_star=0.5)


def test_min_trl_alpha_validation() -> None:
    with pytest.raises(ValueError, match="alpha must be"):
        sh.min_trl(0.5, sr_star=0.0, alpha=0.0)
    with pytest.raises(ValueError, match="alpha must be"):
        sh.min_trl(0.5, sr_star=0.0, alpha=1.0)


# ---------------------------------------------------------------------------
# _normal_ppf_one_sided spot check
# ---------------------------------------------------------------------------


def test_normal_ppf_known_quantile() -> None:
    z = sh._normal_ppf_one_sided(0.05)
    assert abs(z - 1.6448536269514722) < 1e-6
    z = sh._normal_ppf_one_sided(0.025)
    assert abs(z - 1.959963984540054) < 1e-6
