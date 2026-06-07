"""Property tests for fractional differentiation (López de Prado ch. 5)."""
from __future__ import annotations

import numpy as np

from ml.features.frac_diff import ffd_weights, frac_diff_ffd


def test_weights_start_at_one_and_are_finite() -> None:
    w = ffd_weights(0.4)
    assert w.size >= 1
    # Newest-observation weight (w_0 = 1) is the last element.
    assert w[-1] == 1.0
    assert np.all(np.isfinite(w))


def test_weights_truncate_below_threshold() -> None:
    coarse = ffd_weights(0.5, threshold=1e-2)
    fine = ffd_weights(0.5, threshold=1e-6)
    # A smaller threshold keeps more terms.
    assert fine.size > coarse.size
    # All retained weights (except the trailing w_0=1) exceed the threshold.
    assert np.all(np.abs(coarse[:-1]) >= 1e-2)


def test_d_zero_is_identity() -> None:
    x = np.array([3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0])
    out = frac_diff_ffd(x, 0.0)
    assert np.allclose(out, x)


def test_d_one_matches_first_difference_on_valid_region() -> None:
    x = np.array([3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0])
    out = frac_diff_ffd(x, 1.0)
    expected = np.diff(x)
    valid = ~np.isnan(out)
    # d=1 width is 2 -> first position is nan, rest equal the first difference.
    assert np.isnan(out[0])
    assert np.allclose(out[valid], expected)


def test_warmup_region_is_nan() -> None:
    x = np.arange(50.0)
    out = frac_diff_ffd(x, 0.4)
    width = ffd_weights(0.4).size
    assert np.all(np.isnan(out[: width - 1]))
    assert np.all(np.isfinite(out[width - 1 :]))


def test_returns_all_nan_when_series_shorter_than_window() -> None:
    x = np.array([1.0, 2.0])
    out = frac_diff_ffd(x, 0.3, threshold=1e-8)
    # A tiny threshold forces a wide window that exceeds the 2-point series.
    assert out.shape == x.shape
    assert np.all(np.isnan(out))


def test_fractional_diff_reduces_memory_vs_level() -> None:
    # A random walk (integrated, non-stationary) should become far less
    # autocorrelated after fractional differentiation.
    rng = np.random.default_rng(7)
    walk = np.cumsum(rng.standard_normal(2_000))
    fd = frac_diff_ffd(walk, 0.5)
    fd = fd[~np.isnan(fd)]

    def lag1_autocorr(a: np.ndarray) -> float:
        a = a - a.mean()
        denom = float(np.dot(a, a))
        if denom == 0.0:
            return 0.0
        return float(np.dot(a[:-1], a[1:]) / denom)

    level_ac = lag1_autocorr(walk)
    fd_ac = lag1_autocorr(fd)
    assert abs(fd_ac) < abs(level_ac)


def test_invalid_parameters_raise() -> None:
    import pytest

    with pytest.raises(ValueError):
        ffd_weights(-0.1)
    with pytest.raises(ValueError):
        ffd_weights(0.5, threshold=0.0)
    with pytest.raises(ValueError):
        ffd_weights(0.5, max_width=0)
