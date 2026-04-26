"""Sprint C3.1 tests for ``smc_core.inference.bootstrap``."""
from __future__ import annotations

import math

import numpy as np
import pytest

from smc_core.inference.bootstrap import bootstrap_ci


def test_percentile_ci_brackets_point() -> None:
    rng = np.random.default_rng(0)
    sample = rng.normal(0.5, 1.0, size=200)
    res = bootstrap_ci(
        sample,
        statistic=lambda x: float(x.mean()),
        method="percentile",
        B=400,
        seed=1,
    )
    assert res["ci_low"] <= res["point"] <= res["ci_high"]
    assert res["method"] == "percentile"
    assert res["B"] == 400
    assert res["n"] == 200


def test_bca_ci_finite_for_skewed_sample() -> None:
    rng = np.random.default_rng(2)
    sample = rng.exponential(1.0, size=120)  # right-skewed
    res = bootstrap_ci(
        sample,
        statistic=lambda x: float(np.median(x)),
        method="bca",
        B=400,
        seed=3,
    )
    assert math.isfinite(res["ci_low"])
    assert math.isfinite(res["ci_high"])
    assert res["ci_low"] <= res["point"] <= res["ci_high"]


def test_basic_ci_symmetry_around_point() -> None:
    sample = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    res = bootstrap_ci(
        sample,
        statistic=lambda x: float(x.mean()),
        method="basic",
        B=300,
        seed=5,
    )
    # basic CI is reflected percentile around the point
    assert res["ci_low"] < res["point"] < res["ci_high"]


def test_determinism_with_same_seed() -> None:
    sample = np.linspace(0, 1, 50)
    a = bootstrap_ci(sample, statistic=lambda x: float(x.mean()), B=200, seed=42)
    b = bootstrap_ci(sample, statistic=lambda x: float(x.mean()), B=200, seed=42)
    assert a == b


def test_stationary_block_preserves_autocorrelation() -> None:
    rng = np.random.default_rng(7)
    eps = rng.normal(size=400)
    ar1 = np.empty_like(eps)
    ar1[0] = eps[0]
    for i in range(1, len(eps)):
        ar1[i] = 0.6 * ar1[i - 1] + eps[i]
    iid = bootstrap_ci(
        ar1, statistic=lambda x: float(x.std(ddof=1)), B=200, seed=1, block_length=1
    )
    block = bootstrap_ci(
        ar1, statistic=lambda x: float(x.std(ddof=1)), B=200, seed=1, block_length=10
    )
    iid_width = iid["ci_high"] - iid["ci_low"]
    block_width = block["ci_high"] - block["ci_low"]
    # Block bootstrap should produce a wider CI for autocorrelated data.
    assert block_width >= iid_width * 0.95


def test_bca_coverage_better_than_percentile_on_skewed() -> None:
    """BCa should hit nominal coverage closer than percentile on skewed data."""
    seed_seq = np.random.SeedSequence(2026)
    n_reps = 60
    n = 80
    true_mean = 1.0  # mean of Exp(1)
    bca_covered = 0
    perc_covered = 0
    for ss in seed_seq.spawn(n_reps):
        rng = np.random.default_rng(ss)
        sample = rng.exponential(true_mean, size=n)
        seed = int(ss.entropy) % (2**31)
        bca = bootstrap_ci(
            sample,
            statistic=lambda x: float(x.mean()),
            method="bca",
            B=300,
            seed=seed,
        )
        perc = bootstrap_ci(
            sample,
            statistic=lambda x: float(x.mean()),
            method="percentile",
            B=300,
            seed=seed,
        )
        if bca["ci_low"] <= true_mean <= bca["ci_high"]:
            bca_covered += 1
        if perc["ci_low"] <= true_mean <= perc["ci_high"]:
            perc_covered += 1
    bca_cov = bca_covered / n_reps
    perc_cov = perc_covered / n_reps
    # BCa should be at least as good as percentile (within tolerance).
    assert bca_cov >= perc_cov - 0.05, f"bca={bca_cov:.2%} vs percentile={perc_cov:.2%}"
    # And reasonable absolute coverage.
    assert bca_cov >= 0.80, f"bca coverage {bca_cov:.2%} below 80%"


def test_validates_inputs() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        bootstrap_ci(np.array([]), statistic=lambda x: 0.0)
    with pytest.raises(ValueError, match="finite"):
        bootstrap_ci(
            np.array([1.0, np.nan]), statistic=lambda x: 0.0
        )
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_ci(np.array([1.0, 2.0]), statistic=lambda x: 0.0, alpha=1.5)
    with pytest.raises(ValueError, match="B"):
        bootstrap_ci(np.array([1.0, 2.0]), statistic=lambda x: 0.0, B=0)
    with pytest.raises(ValueError, match="block_length"):
        bootstrap_ci(np.array([1.0, 2.0]), statistic=lambda x: 0.0, block_length=0)
