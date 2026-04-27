"""Regression: kolmogorov_q numerical guard for very small lambda.

C-sprint deep-review pass-2: the alternating series

    Q(lambda) = 2 * sum_{k=1..} (-1)^(k-1) * exp(-2 k^2 lambda^2)

does not converge within 100 terms when lambda is very small (~0.01)
because each term stays close to 1 in magnitude. The partial sum then
oscillates between ~0 and ~1 depending on the parity of the truncation
point, producing a wildly unstable p-value at the regime where samples
are essentially identical (which should yield p ~= 1 = no drift).

This test pins the small-lambda guard at lambda < 0.18 (Numerical
Recipes Sec. 14.3.3 cutoff) so any future caller that drops or moves
the guard breaks loudly.
"""

from __future__ import annotations

import math

from scripts._kolmogorov import kolmogorov_q, kolmogorov_sf_two_sample


def test_kolmogorov_q_returns_one_for_small_lambda() -> None:
    """All lambda below the 0.18 cutoff must short-circuit to p=1.0."""
    for lam in (1e-9, 1e-6, 0.001, 0.01, 0.05, 0.1, 0.179):
        assert kolmogorov_q(lam) == 1.0, f"lam={lam} should clamp to 1.0"


def test_kolmogorov_q_continues_to_use_series_above_cutoff() -> None:
    """At lambda >= 0.18 the series is used; values must be in [0, 1]."""
    for lam in (0.2, 0.3, 0.5, 1.0, 2.0):
        p = kolmogorov_q(lam)
        assert 0.0 <= p <= 1.0
    # Large lambda → near-zero tail probability.
    assert kolmogorov_q(2.0) < 1e-3


def test_kolmogorov_q_lambda_zero_returns_one() -> None:
    assert kolmogorov_q(0.0) == 1.0
    assert kolmogorov_q(-1.0) == 1.0


def test_two_sample_sf_near_identical_samples_returns_one() -> None:
    """Tiny K-S statistic on a non-trivial sample must NOT trigger drift.

    Without the small-lambda guard, ``d=1e-4`` at ``n_eff=100`` produces
    ``lam ~= 1e-3`` and the alternating series oscillation makes the
    p-value bounce; this test ensures the guard returns ~1.0 instead.
    """
    p = kolmogorov_sf_two_sample(d=1e-4, n_eff=100.0)
    assert math.isfinite(p)
    assert p == 1.0
