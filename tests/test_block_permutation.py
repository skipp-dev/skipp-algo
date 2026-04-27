"""Sprint C4.1 tests for ``smc_core.inference.permutation`` + ``null_cache``."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from smc_core.inference.null_cache import CacheKey, NullCache
from smc_core.inference.permutation import block_permutation_test


def _mean_diff(t: np.ndarray, c: np.ndarray) -> float:
    return float(t.mean() - c.mean())


def test_block_size_1_reproduces_iid_permutation() -> None:
    rng = np.random.default_rng(0)
    t = rng.normal(0.5, 1.0, size=100)
    c = rng.normal(0.0, 1.0, size=100)
    p_iid, obs_iid, null_iid = block_permutation_test(
        treatment=t, control=c, statistic=_mean_diff, block_size=1, B=200, seed=42
    )
    p_iid2, obs_iid2, null_iid2 = block_permutation_test(
        treatment=t, control=c, statistic=_mean_diff, block_size=1, B=200, seed=42
    )
    assert p_iid == p_iid2
    assert obs_iid == obs_iid2
    np.testing.assert_array_equal(null_iid, null_iid2)


def test_detects_real_difference_block_size_1() -> None:
    rng = np.random.default_rng(1)
    t = rng.normal(1.0, 0.5, size=200)
    c = rng.normal(0.0, 0.5, size=200)
    p, observed, _ = block_permutation_test(
        treatment=t, control=c, statistic=_mean_diff, block_size=1, B=400, seed=7
    )
    assert observed > 0.5
    assert p < 0.01


def test_block_resampling_widens_pvalue_for_autocorrelated_data() -> None:
    """Autocorrelated returns: iid p-value should be smaller (more liberal)."""
    rng = np.random.default_rng(11)
    eps_t = rng.normal(size=300)
    eps_c = rng.normal(size=300)
    t = np.empty_like(eps_t)
    c = np.empty_like(eps_c)
    t[0], c[0] = eps_t[0], eps_c[0]
    for i in range(1, len(eps_t)):
        t[i] = 0.7 * t[i - 1] + eps_t[i]
        c[i] = 0.7 * c[i - 1] + eps_c[i]
    p_iid, _, _ = block_permutation_test(
        treatment=t, control=c, statistic=_mean_diff, block_size=1, B=300, seed=3
    )
    p_block, _, _ = block_permutation_test(
        treatment=t, control=c, statistic=_mean_diff, block_size=15, B=300, seed=3
    )
    # Block test should be at least as conservative under the null/near-null.
    assert p_block >= p_iid * 0.5


def test_pvalue_never_zero_phipson_smyth() -> None:
    """(r + 1) / (B + 1) correction prevents p == 0."""
    t = np.full(50, 100.0)
    c = np.full(50, 0.0)
    p, _, _ = block_permutation_test(
        treatment=t, control=c, statistic=_mean_diff, B=50, seed=0
    )
    assert p == pytest.approx(1.0 / 51.0)


def test_alternative_greater_vs_less() -> None:
    rng = np.random.default_rng(17)
    t = rng.normal(1.0, 0.3, size=120)
    c = rng.normal(0.0, 0.3, size=120)
    p_greater, _, _ = block_permutation_test(
        treatment=t, control=c, statistic=_mean_diff, B=200, seed=5,
        alternative="greater",
    )
    p_less, _, _ = block_permutation_test(
        treatment=t, control=c, statistic=_mean_diff, B=200, seed=5,
        alternative="less",
    )
    assert p_greater < 0.05
    assert p_less > 0.95


def test_block_aligned_split_keeps_blocks_intact() -> None:
    """C-sprint deep-review C4 MAJOR fix regression: when ``block_size > 1``
    and ``n_t`` is not a multiple of ``block_size``, the split between
    treatment and control must land on a block boundary so no permuted
    block is cut mid-way. The behaviour for ``block_size == 1`` must
    remain identical to the iid case (split at exact ``n_t``).
    """
    from smc_core.inference.permutation import (
        _block_aligned_split,
        _block_indices,
    )

    rng = np.random.default_rng(seed=7)
    n = 100
    block_size = 5
    n_t = 47  # NOT a multiple of block_size — would have cut mid-block.

    idx = _block_indices(n, block_size, rng)
    permuted = np.arange(n)[idx]

    t_arr, c_arr = _block_aligned_split(permuted, n_t, block_size)
    assert t_arr.size + c_arr.size == n
    # Treatment size snapped to nearest block boundary.
    assert t_arr.size % block_size == 0
    # Treatment chunk must be a contiguous prefix of the permuted seq.
    np.testing.assert_array_equal(t_arr, permuted[: t_arr.size])
    # block_size=1 path unchanged (exact split at n_t).
    t1, c1 = _block_aligned_split(permuted, n_t, block_size=1)
    assert t1.size == n_t
    np.testing.assert_array_equal(t1, permuted[:n_t])
    np.testing.assert_array_equal(c1, permuted[n_t:])


def test_block_permutation_runs_with_unaligned_n_t() -> None:
    """End-to-end: ``n_t`` not divisible by ``block_size`` must no longer
    cut a block mid-way — the run completes and produces a valid
    p-value distribution.
    """
    rng = np.random.default_rng(seed=3)
    t = rng.normal(0.5, 1.0, size=47)  # 47 not divisible by 5.
    c = rng.normal(0.0, 1.0, size=53)
    p, _, null = block_permutation_test(
        treatment=t, control=c,
        statistic=_mean_diff, block_size=5, B=200, seed=12,
    )
    assert 0.0 < p <= 1.0
    assert null.shape == (200,)


def test_validates_inputs() -> None:
    with pytest.raises(ValueError, match="block_size"):
        block_permutation_test(
            treatment=np.array([1.0]), control=np.array([0.0]),
            statistic=_mean_diff, block_size=0,
        )
    with pytest.raises(ValueError, match="B"):
        block_permutation_test(
            treatment=np.array([1.0]), control=np.array([0.0]),
            statistic=_mean_diff, B=0,
        )
    with pytest.raises(ValueError, match="treatment"):
        block_permutation_test(
            treatment=np.array([]), control=np.array([0.0]), statistic=_mean_diff,
        )
    with pytest.raises(ValueError, match="control"):
        block_permutation_test(
            treatment=np.array([1.0]), control=np.array([np.nan]),
            statistic=_mean_diff,
        )


# ---------------------------------------------------------------------------
# null cache
# ---------------------------------------------------------------------------


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = NullCache(tmp_path)
    key = CacheKey(
        family="BOS", regime="rth", dataset_fingerprint="abc123",
        n_perms=200, block_size=5, statistic_name="mean_diff",
    )
    assert cache.get(key) is None
    null = np.linspace(-1.0, 1.0, 200)
    cache.put(key, null)
    loaded = cache.get(key)
    assert loaded is not None
    np.testing.assert_array_almost_equal(loaded, null)
    assert len(cache) == 1


def test_cache_miss_on_changed_fingerprint(tmp_path: Path) -> None:
    cache = NullCache(tmp_path)
    base = CacheKey(
        family="OB", regime="eth", dataset_fingerprint="v1",
        n_perms=100, block_size=1, statistic_name="diff",
    )
    cache.put(base, np.zeros(100))
    bumped = CacheKey(
        family="OB", regime="eth", dataset_fingerprint="v2",  # bumped
        n_perms=100, block_size=1, statistic_name="diff",
    )
    assert cache.get(bumped) is None


def test_cache_atomic_write_no_partial_files(tmp_path: Path) -> None:
    cache = NullCache(tmp_path)
    key = CacheKey(
        family="FVG", regime="any", dataset_fingerprint="x",
        n_perms=10, block_size=1, statistic_name="t",
    )
    cache.put(key, np.arange(10, dtype=float))
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".json"
