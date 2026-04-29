"""Tests for ``scripts/bootstrap_methods.py`` (Sprint C3 / T2).

Coverage targets per ``docs/SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md``:

- determinism (same seed -> identical resamples)
- shape contract (B, n)
- statistical sanity: stationary block bootstrap on AR(1) with rho=0.3
  produces wider Sharpe-spread than IID bootstrap
- input validation
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts import bootstrap_methods as bm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ar1_returns(n: int, rho: float, sigma: float, seed: int) -> np.ndarray:
    """Generate an AR(1) return series with auto-correlation ``rho``."""

    rng = np.random.default_rng(seed)
    eps = rng.normal(loc=0.0, scale=sigma, size=n)
    out = np.empty(n, dtype=np.float64)
    out[0] = eps[0]
    for i in range(1, n):
        out[i] = rho * out[i - 1] + eps[i]
    return out


# ---------------------------------------------------------------------------
# Shape + determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("iid", {}),
        ("stationary", {"mean_block_length": 5}),
        ("circular", {"mean_block_length": 5}),
    ],
)
def test_resample_shape(method: str, kwargs: dict) -> None:
    returns = np.linspace(-0.01, 0.02, num=120)
    out = bm.make_resamples(returns, method=method, B=128, seed=7, **kwargs)
    assert out.shape == (128, 120)
    assert out.dtype == np.float64


@pytest.mark.parametrize("method", ["iid", "stationary", "circular"])
def test_determinism_same_seed_identical(method: str) -> None:
    returns = np.linspace(-0.01, 0.02, num=120)
    a = bm.make_resamples(returns, method=method, B=64, seed=11)
    b = bm.make_resamples(returns, method=method, B=64, seed=11)
    np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize("method", ["iid", "stationary", "circular"])
def test_determinism_different_seed_diverges(method: str) -> None:
    returns = np.linspace(-0.01, 0.02, num=120)
    a = bm.make_resamples(returns, method=method, B=64, seed=11)
    b = bm.make_resamples(returns, method=method, B=64, seed=12)
    assert not np.array_equal(a, b)


# ---------------------------------------------------------------------------
# Resamples actually draw from the input population
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["iid", "stationary", "circular"])
def test_values_are_subset_of_input(method: str) -> None:
    """Every resampled value must be one of the original observations."""

    returns = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = bm.make_resamples(returns, method=method, B=200, seed=3, mean_block_length=2)
    assert np.isin(out, returns).all()


@pytest.mark.parametrize("method", ["iid", "stationary", "circular"])
def test_resample_mean_close_to_population_mean(method: str) -> None:
    """For large B, mean of bootstrap means converges to sample mean."""

    rng = np.random.default_rng(123)
    returns = rng.normal(loc=0.001, scale=0.01, size=200)
    out = bm.make_resamples(returns, method=method, B=2000, seed=99, mean_block_length=5)
    boot_means = out.mean(axis=1)
    np.testing.assert_allclose(boot_means.mean(), returns.mean(), atol=5e-4)


# ---------------------------------------------------------------------------
# Statistical property: stationary bootstrap respects auto-correlation
# ---------------------------------------------------------------------------


def _sharpe(arr: np.ndarray) -> np.ndarray:
    """Per-row Sharpe, periodic (no annualization)."""

    mu = arr.mean(axis=1)
    sd = arr.std(axis=1, ddof=1)
    # Guard against near-zero std (will not happen on AR(1) data).
    return mu / np.where(sd == 0, np.nan, sd)


def test_stationary_widens_sharpe_distribution_vs_iid_on_ar1() -> None:
    """On AR(1) with rho=0.3, stationary bootstrap produces wider Sharpe spread.

    Rationale (Politis-Romano / Ledoit-Wolf): IID bootstrap destroys
    auto-correlation and therefore *underestimates* the variance of
    Sharpe-like statistics on serially correlated returns. The stationary
    block bootstrap preserves within-block dependence, so the Sharpe
    distribution across resamples should be visibly wider.
    """

    returns = _ar1_returns(n=200, rho=0.3, sigma=0.01, seed=42)

    iid = bm.iid_bootstrap(returns, B=2000, seed=7)
    stat = bm.stationary_block_bootstrap(
        returns, mean_block_length=5, B=2000, seed=7
    )

    iid_std = float(np.nanstd(_sharpe(iid), ddof=1))
    stat_std = float(np.nanstd(_sharpe(stat), ddof=1))

    # Expect at least 5% wider spread; in practice the gap is 10-25%.
    assert stat_std > iid_std * 1.05, (
        f"stationary spread {stat_std:.4f} not wider than iid {iid_std:.4f}"
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["iid", "stationary", "circular"])
def test_empty_input_rejected(method: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        bm.make_resamples(np.array([]), method=method, B=10, seed=1)


@pytest.mark.parametrize("method", ["iid", "stationary", "circular"])
def test_non_finite_input_rejected(method: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        bm.make_resamples(np.array([1.0, np.nan, 2.0]), method=method, B=10, seed=1)


@pytest.mark.parametrize("method", ["iid", "stationary", "circular"])
def test_higher_dim_input_rejected(method: str) -> None:
    with pytest.raises(ValueError, match="1-D"):
        bm.make_resamples(np.zeros((3, 4)), method=method, B=10, seed=1)


@pytest.mark.parametrize("method", ["iid", "stationary", "circular"])
def test_zero_B_rejected(method: str) -> None:
    with pytest.raises(ValueError, match="B must be positive"):
        bm.make_resamples(np.array([1.0, 2.0]), method=method, B=0, seed=1)


def test_stationary_invalid_block_length_rejected() -> None:
    with pytest.raises(ValueError, match="mean_block_length must be >= 1"):
        bm.stationary_block_bootstrap(np.array([1.0]), mean_block_length=0, B=5)


def test_circular_invalid_block_length_rejected() -> None:
    with pytest.raises(ValueError, match="block_length must be >= 1"):
        bm.circular_block_bootstrap(np.array([1.0]), block_length=0, B=5)


def test_unknown_method_rejected() -> None:
    with pytest.raises(ValueError, match="unknown bootstrap method"):
        bm.make_resamples(np.array([1.0, 2.0]), method="bogus", B=5, seed=1)  # type: ignore[arg-type]
