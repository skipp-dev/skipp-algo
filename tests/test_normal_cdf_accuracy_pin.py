"""Numerical accuracy pin for ``_normal_cdf``.

``scripts.run_ab_comparison._normal_cdf`` is a tiny ``math.erf``-based
standard-normal CDF. It backs the one-sided p-values produced by
``_two_proportion_z_pvalue``, which in turn feed the BH-FDR layer
(``digest['fdr']``). Any silent drift here (e.g. someone "improves"
the implementation with a different approximation) would shift every
p-value in the digest. This module pins the function against textbook
reference values.

The pin is intentionally tight (1e-9 absolute tolerance): ``math.erf``
is deterministic across Python 3.13 builds, so a failure here means
either the implementation or its callable identity changed — both
warrant explicit review.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from scripts.run_ab_comparison import _normal_cdf

# Reference values from a 64-bit ``scipy.stats.norm.cdf`` evaluation,
# rounded to 15 significant digits. ``math.erf`` is implemented on
# ``libm``'s high-precision erf, so the ``0.5 * (1 + erf(x / sqrt(2)))``
# formula matches scipy to ~1e-15. A polynomial-approximation
# replacement (Abramowitz & Stegun, etc.) would diverge by ~1e-7 or
# more and trip the 1e-9 tolerance below.
_REFERENCE_POINTS = (
    (-3.0, 0.001349898031630),
    (-2.5760, 0.004997532315735),
    (-1.96, 0.024997895148220),     # ~2.5%-quantile (-z_{0.975})
    (-1.6449, 0.049995217468346),   # ~5%-quantile
    (-1.0, 0.158655253931457),
    (-0.5, 0.308537538725987),
    (0.0, 0.500000000000000),
    (0.5, 0.691462461274013),
    (1.0, 0.841344746068543),
    (1.6449, 0.950004782531654),
    (1.96, 0.975002104851780),
    (2.5760, 0.995002467684265),
    (3.0, 0.998650101968370),
)


@pytest.mark.parametrize("x,expected", _REFERENCE_POINTS, ids=lambda v: f"{v}")
def test_normal_cdf_matches_reference(x: float, expected: float) -> None:
    """``_normal_cdf`` must agree with reference values to 1e-9."""
    actual = _normal_cdf(x)
    assert math.isclose(actual, expected, abs_tol=1e-9), (
        f"_normal_cdf({x}) = {actual!r}, expected {expected!r} "
        f"(|delta| = {abs(actual - expected)!r}). If the implementation "
        "changed intentionally, update the reference values from a 64-bit "
        "scipy.stats.norm.cdf evaluation and bump the BH-FDR schema "
        "version (the p-values feed digest['fdr']/digest['fdr_calibration'])."
    )


def test_normal_cdf_zero_is_exactly_one_half() -> None:
    """``_normal_cdf(0)`` must be **exactly** 0.5, not approximately."""
    assert _normal_cdf(0.0) == 0.5


def test_normal_cdf_symmetry() -> None:
    """``_normal_cdf(-x) + _normal_cdf(x) == 1`` for all x."""
    for x in (0.1, 0.5, 1.0, 1.96, 2.5760, 3.0, 5.0, 10.0):
        s = _normal_cdf(-x) + _normal_cdf(x)
        assert math.isclose(s, 1.0, abs_tol=1e-12), (
            f"symmetry violated at x={x}: _normal_cdf(-x) + _normal_cdf(x) = {s!r}"
        )


def test_normal_cdf_monotonic() -> None:
    """``_normal_cdf`` must be (weakly) monotonically increasing."""
    xs = [-5.0, -3.0, -1.0, -0.5, 0.0, 0.5, 1.0, 3.0, 5.0]
    ys = [_normal_cdf(x) for x in xs]
    for prev, curr in pairwise(ys):
        assert prev <= curr, f"non-monotonic: {ys}"


def test_normal_cdf_bounds() -> None:
    """``_normal_cdf`` output must lie in [0, 1] for finite extremes."""
    assert 0.0 <= _normal_cdf(-50.0) <= 1e-9
    assert 1.0 - 1e-9 <= _normal_cdf(50.0) <= 1.0
