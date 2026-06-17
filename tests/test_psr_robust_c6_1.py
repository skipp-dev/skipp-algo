"""Sprint C6.1 tests for psr_robust (slippage + robust moments)."""
from __future__ import annotations

import random

import pytest

from open_prep.psr_robust import (
    compute_psr_minIS,
    probabilistic_sharpe_robust,
)
from open_prep.stats_helpers import probabilistic_sharpe


def _seeded_returns(n: int, seed: int = 42, mu: float = 0.001, sigma: float = 0.01):
    rng = random.Random(seed)
    return [rng.gauss(mu, sigma) for _ in range(n)]


# ---------------------------------------------------------------------------
# Slippage / Min-IS
# ---------------------------------------------------------------------------


def test_psr_minIS_no_slippage_matches_baseline() -> None:
    returns = _seeded_returns(200)
    base = probabilistic_sharpe(returns, sr_star=0.0)
    out = compute_psr_minIS(returns, sr_star=0.0)
    assert out["psr"] == pytest.approx(base["psr"])
    assert out["psr_brutto"] == pytest.approx(base["psr"])
    assert out["slippage_adjusted"] is False


def test_psr_minIS_with_positive_slippage_lowers_psr() -> None:
    returns = _seeded_returns(300, mu=0.002)
    slippage = [5.0] * len(returns)  # 5 bps per bar adverse
    out = compute_psr_minIS(returns, slippage_bps_series=slippage, sr_star=0.0)
    assert out["slippage_adjusted"] is True
    assert out["psr"] < out["psr_brutto"], (out["psr"], out["psr_brutto"])
    assert out["mean_slippage_bps"] == pytest.approx(5.0)


def test_psr_minIS_zero_slippage_equals_brutto() -> None:
    returns = _seeded_returns(150, mu=0.001)
    out = compute_psr_minIS(
        returns, slippage_bps_series=[0.0] * len(returns), sr_star=0.0
    )
    assert out["psr"] == pytest.approx(out["psr_brutto"])


def test_psr_minIS_length_validation() -> None:
    with pytest.raises(ValueError, match="slippage_bps_series length"):
        compute_psr_minIS(
            _seeded_returns(50), slippage_bps_series=[1.0, 2.0], sr_star=0.0
        )


# ---------------------------------------------------------------------------
# Robust moments
# ---------------------------------------------------------------------------


def test_robust_sample_estimator_is_baseline() -> None:
    returns = _seeded_returns(200)
    base = probabilistic_sharpe(returns, sr_star=0.0)
    out = probabilistic_sharpe_robust(returns, sr_star=0.0, moments_estimator="sample")
    assert out["psr"] == pytest.approx(base["psr"])
    assert out["sharpe_hat"] == pytest.approx(base["sharpe_hat"])


def test_robust_winsorized_stable_under_outlier_injection() -> None:
    returns = _seeded_returns(500, mu=0.001, sigma=0.005)
    # Inject 4 huge outlier bars (~10 sigma each)
    contaminated = list(returns)
    for i in (50, 150, 300, 450):
        contaminated[i] = 0.5  # gigantic positive bar

    sample = probabilistic_sharpe(contaminated, sr_star=0.0)
    robust = probabilistic_sharpe_robust(
        contaminated, sr_star=0.0, moments_estimator="winsorized", winsor_alpha=0.05
    )
    # Sharpe estimate is the same (point statistic unchanged).
    assert robust["sharpe_hat"] == pytest.approx(sample["sharpe_hat"])
    # The sample kurtosis exploded from outliers; winsorized kurtosis must be smaller.
    assert robust["kurtosis"] < sample["kurtosis"]


def test_robust_winsorized_recovers_clean_psr_after_outlier() -> None:
    """Winsorized PSR moves toward clean PSR vs sample PSR after contamination.

    Use sr_star close to clean Sharpe so PSR is not saturated at ~1, where
    a few extra basis points are invisible. Under that regime the robust
    estimator should be measurably closer to the clean PSR than the sample
    estimator (kurtosis blow-up shrinks the sample PSR).
    """
    clean = _seeded_returns(400, mu=0.001, sigma=0.01)
    contaminated = list(clean)
    for i in (40, 120, 220, 350):
        contaminated[i] = 0.2  # outlier ~20 sigma

    base = probabilistic_sharpe(clean, sr_star=0.0)
    sr_clean = base["sharpe_hat"]
    # Pick sr_star just above the clean Sharpe so PSR is non-saturated.
    sr_star = sr_clean * 1.05

    base_clean = probabilistic_sharpe(clean, sr_star=sr_star)["psr"]
    sample_contam = probabilistic_sharpe(contaminated, sr_star=sr_star)["psr"]
    robust_contam = probabilistic_sharpe_robust(
        contaminated,
        sr_star=sr_star,
        moments_estimator="winsorized",
        winsor_alpha=0.025,
    )["psr"]
    # Robust must be at least as close to clean as sample.
    assert abs(robust_contam - base_clean) <= abs(sample_contam - base_clean) + 1e-9


def test_robust_winsor_alpha_validation() -> None:
    returns = _seeded_returns(50)
    with pytest.raises(ValueError, match="alpha"):
        probabilistic_sharpe_robust(
            returns, moments_estimator="winsorized", winsor_alpha=0.0
        )
    with pytest.raises(ValueError, match="alpha"):
        probabilistic_sharpe_robust(
            returns, moments_estimator="winsorized", winsor_alpha=0.5
        )


def test_robust_unknown_estimator() -> None:
    with pytest.raises(ValueError, match="moments_estimator"):
        probabilistic_sharpe_robust(
            _seeded_returns(50), moments_estimator="bogus",  # type: ignore[arg-type]
        )


def test_robust_too_few_observations() -> None:
    with pytest.raises(ValueError, match="at least"):
        probabilistic_sharpe_robust([0.01, 0.02], sr_star=0.0)


def test_robust_constant_series_raises() -> None:
    with pytest.raises(ValueError, match="variance is zero"):
        probabilistic_sharpe_robust(
            [0.01] * 50, sr_star=0.0, moments_estimator="winsorized"
        )
