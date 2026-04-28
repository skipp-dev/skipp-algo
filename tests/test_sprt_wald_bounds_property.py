"""Property test: SPRTConfig Wald-bound formulas + invariants.

``scripts.smc_sprt_stop_rule.SPRTConfig`` exposes ``upper_bound``
(Wald A = ln((1-β)/α)) and ``lower_bound`` (Wald B = ln(β/(1-α))).
These two formulas underpin every SPRT decision in the measurement
runtime — a stealth refactor that swaps the numerator/denominator,
flips the sign, or substitutes an "equivalent" expression would
silently invert promote/hold/rollback decisions for the SPRT layer.

This module pins:
1. The closed-form formulas against a curated grid of (alpha, beta)
   pairs spanning the validation range (alpha, beta in (0, 0.5)).
2. Sign invariants: upper > 0 (accept-H1 threshold) and lower < 0
   (accept-H0 threshold) for any valid config.
3. Asymmetry: upper != lower (degeneracy guard).
"""

from __future__ import annotations

import math
from itertools import product

import pytest

from scripts.smc_sprt_stop_rule import SPRTConfig

# Grid spans the documented valid range: alpha, beta in (0, 0.5).
# Pre-PR-#117 callers used (0.05, 0.20); the production refresh runs
# tighter (0.025, 0.10). The grid below covers both plus extremes.
_ALPHAS = (0.001, 0.01, 0.025, 0.05, 0.10, 0.25, 0.49)
_BETAS = (0.001, 0.05, 0.10, 0.20, 0.25, 0.49)


@pytest.mark.parametrize("alpha,beta", list(product(_ALPHAS, _BETAS)))
def test_wald_upper_bound_matches_closed_form(alpha: float, beta: float) -> None:
    """``upper_bound == ln((1 - beta) / alpha)`` for every (alpha, beta)."""
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=alpha, beta=beta)
    expected = math.log((1.0 - beta) / alpha)
    assert math.isclose(cfg.upper_bound, expected, rel_tol=1e-12), (
        f"upper_bound formula drifted at (alpha={alpha}, beta={beta}): "
        f"got {cfg.upper_bound!r}, expected {expected!r}. "
        "If the SPRT bound formula changed intentionally, supersede the "
        "Wald-SPRT design note and update both bounds together."
    )


@pytest.mark.parametrize("alpha,beta", list(product(_ALPHAS, _BETAS)))
def test_wald_lower_bound_matches_closed_form(alpha: float, beta: float) -> None:
    """``lower_bound == ln(beta / (1 - alpha))`` for every (alpha, beta)."""
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=alpha, beta=beta)
    expected = math.log(beta / (1.0 - alpha))
    assert math.isclose(cfg.lower_bound, expected, rel_tol=1e-12), (
        f"lower_bound formula drifted at (alpha={alpha}, beta={beta}): "
        f"got {cfg.lower_bound!r}, expected {expected!r}. "
        "If the SPRT bound formula changed intentionally, supersede the "
        "Wald-SPRT design note and update both bounds together."
    )


@pytest.mark.parametrize("alpha,beta", list(product(_ALPHAS, _BETAS)))
def test_wald_bounds_have_correct_signs(alpha: float, beta: float) -> None:
    """``upper_bound > 0`` (accept-H1) and ``lower_bound < 0`` (accept-H0).

    Any valid config (alpha, beta in (0, 0.5)) has (1-beta)/alpha > 1
    so its log is positive, and beta/(1-alpha) < 1 so its log is negative.
    A sign flip here would invert every SPRT decision.
    """
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=alpha, beta=beta)
    assert cfg.upper_bound > 0.0, (
        f"upper_bound must be positive (accept-H1 threshold), "
        f"got {cfg.upper_bound!r} at (alpha={alpha}, beta={beta})"
    )
    assert cfg.lower_bound < 0.0, (
        f"lower_bound must be negative (accept-H0 threshold), "
        f"got {cfg.lower_bound!r} at (alpha={alpha}, beta={beta})"
    )


@pytest.mark.parametrize("alpha,beta", list(product(_ALPHAS, _BETAS)))
def test_wald_bounds_strictly_separated(alpha: float, beta: float) -> None:
    """``upper_bound > lower_bound`` — degenerate bounds break the test."""
    cfg = SPRTConfig(p0=0.5, p1=0.6, alpha=alpha, beta=beta)
    assert cfg.upper_bound > cfg.lower_bound, (
        f"bounds collapsed at (alpha={alpha}, beta={beta}): "
        f"upper={cfg.upper_bound!r}, lower={cfg.lower_bound!r}"
    )


def test_tighter_alpha_widens_upper_bound() -> None:
    """Smaller alpha → harder to accept H1 → larger upper_bound."""
    loose = SPRTConfig(p0=0.5, p1=0.6, alpha=0.10, beta=0.20)
    tight = SPRTConfig(p0=0.5, p1=0.6, alpha=0.01, beta=0.20)
    assert tight.upper_bound > loose.upper_bound


def test_tighter_beta_widens_lower_bound() -> None:
    """Smaller beta → harder to accept H0 → smaller (more negative) lower_bound."""
    loose = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.20)
    tight = SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.01)
    assert tight.lower_bound < loose.lower_bound
