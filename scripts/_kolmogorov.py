"""Shared Kolmogorov-distribution survival function (no scipy).

The convergent series ``Q(λ) = 2 Σ_{k=1..} (-1)^(k-1) exp(-2 k² λ²)``
appears in two places in the C-sprint stack (drift_alert.py and
compute_live_drift.py); this module is the single implementation both
should consume so the asymptotic K-S p-value stays consistent.

References
----------
- Numerical Recipes, §14.3.3.
- https://en.wikipedia.org/wiki/Kolmogorov%E2%80%93Smirnov_test
"""

from __future__ import annotations

import math

__all__ = ["kolmogorov_q", "kolmogorov_sf_two_sample"]


def kolmogorov_q(lam: float) -> float:
    """Tail of the Kolmogorov distribution Q(λ); clamped to [0, 1]."""
    if lam <= 0.0:
        return 1.0
    total = 0.0
    sign = 1.0
    for k in range(1, 101):
        term = sign * math.exp(-2.0 * (k * lam) ** 2)
        total += term
        if abs(term) < 1e-12:
            break
        sign = -sign
    p = 2.0 * total
    return max(0.0, min(1.0, p))


def kolmogorov_sf_two_sample(d: float, n_eff: float) -> float:
    """Two-sample K-S asymptotic survival function with the Stephens correction.

    ``n_eff = n_a · n_b / (n_a + n_b)`` is the harmonic-mean sample
    size; the Stephens correction term ``(sqrt(n_eff) + 0.12 + 0.11 / sqrt(n_eff))``
    matches scipy.stats.kstwobign.sf and the Press et al. recipe.
    """
    if n_eff <= 0.0 or d <= 0.0:
        return 1.0
    sqrt_n = math.sqrt(n_eff)
    lam = (sqrt_n + 0.12 + 0.11 / sqrt_n) * d
    return kolmogorov_q(lam)
