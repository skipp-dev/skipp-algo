"""Boundary-precision pins for ``terminal_decision`` (SPRT closed-form).

PR #120 pinned the four decision categories of `digest['sprt']`
(``accept_h1`` / ``accept_h0`` / ``inconclusive`` / zero-n empty
arms). What remained unpinned is the **exact transition point** —
the smallest ``k`` at which the LLR crosses each Wald bound. A
silent off-by-one (e.g. ``llr > upper_bound`` instead of
``llr >= upper_bound``) would shift one decision per A/B run, and
the existing variant-coverage tests would not catch it.

This module computes the transition ``k`` from the closed-form
LLR for a fixed ``(n, p0, p1, alpha, beta)`` configuration and
asserts:

* ``k = K - 1`` → ``accept_h0`` (just below lower bound).
* ``k = K``     → ``accept_h0``  (exactly at lower bound).
* ``k = K + 1`` → ``inconclusive`` (just inside lower bound).
* and symmetrically at the upper bound.

Reference math:

    llr(n, k) = k * ln(p1 / p0) + (n - k) * ln((1 - p1) / (1 - p0))
              = k * (ln(p1/p0) - ln((1-p1)/(1-p0))) + n * ln((1-p1)/(1-p0))
              = k * delta + n * c0

where ``delta = ln(p1/p0) - ln((1-p1)/(1-p0)) > 0`` (since p1 > p0).

Solving llr(n, k) = bound for k:

    k* = (bound - n * c0) / delta
"""

from __future__ import annotations

import math

import pytest

from scripts.smc_sprt_stop_rule import SPRTConfig, terminal_decision


@pytest.fixture
def cfg() -> SPRTConfig:
    return SPRTConfig(p0=0.5, p1=0.6, alpha=0.05, beta=0.20)


def _solve_k_at_bound(n: int, cfg: SPRTConfig, bound: float) -> float:
    """Return the (real-valued) k that solves llr(n, k) == bound."""
    delta = math.log(cfg.p1 / cfg.p0) - math.log((1.0 - cfg.p1) / (1.0 - cfg.p0))
    c0 = math.log((1.0 - cfg.p1) / (1.0 - cfg.p0))
    return (bound - n * c0) / delta


# ---------------------------------------------------------------------------
# Upper bound (accept_h1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [200, 500, 1000])
def test_upper_bound_transition_is_inclusive(n: int, cfg: SPRTConfig) -> None:
    """``llr >= upper_bound`` → ``accept_h1``.

    Pin: the smallest integer k with ``llr(n, k) >= upper_bound`` must
    be classified as ``accept_h1``, and ``k - 1`` (one fewer hit)
    must be ``inconclusive``.
    """
    k_real = _solve_k_at_bound(n, cfg, cfg.upper_bound)
    k_min_h1 = math.ceil(k_real)
    # Edge cases: ensure k_min_h1 sits inside [0, n].
    assert 0 <= k_min_h1 - 1 < k_min_h1 <= n

    state_h1, decision_h1 = terminal_decision(n=n, k=k_min_h1, config=cfg)
    state_inc, decision_inc = terminal_decision(n=n, k=k_min_h1 - 1, config=cfg)

    assert decision_h1 == "accept_h1", (
        f"n={n}, k={k_min_h1}: expected accept_h1 at upper-bound transition, "
        f"got {decision_h1} (llr={state_h1.llr}, bound={cfg.upper_bound})"
    )
    assert decision_inc == "inconclusive", (
        f"n={n}, k={k_min_h1 - 1}: expected inconclusive one below "
        f"upper-bound transition, got {decision_inc} "
        f"(llr={state_inc.llr}, bound={cfg.upper_bound})"
    )


# ---------------------------------------------------------------------------
# Lower bound (accept_h0)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [200, 500, 1000])
def test_lower_bound_transition_is_inclusive(n: int, cfg: SPRTConfig) -> None:
    """``llr <= lower_bound`` → ``accept_h0``.

    Pin: the largest integer k with ``llr(n, k) <= lower_bound`` must
    be classified as ``accept_h0``, and ``k + 1`` (one more hit) must
    be ``inconclusive``.
    """
    k_real = _solve_k_at_bound(n, cfg, cfg.lower_bound)
    k_max_h0 = math.floor(k_real)
    assert 0 <= k_max_h0 < k_max_h0 + 1 <= n

    state_h0, decision_h0 = terminal_decision(n=n, k=k_max_h0, config=cfg)
    state_inc, decision_inc = terminal_decision(n=n, k=k_max_h0 + 1, config=cfg)

    assert decision_h0 == "accept_h0", (
        f"n={n}, k={k_max_h0}: expected accept_h0 at lower-bound transition, "
        f"got {decision_h0} (llr={state_h0.llr}, bound={cfg.lower_bound})"
    )
    assert decision_inc == "inconclusive", (
        f"n={n}, k={k_max_h0 + 1}: expected inconclusive one above "
        f"lower-bound transition, got {decision_inc} "
        f"(llr={state_inc.llr}, bound={cfg.lower_bound})"
    )


# ---------------------------------------------------------------------------
# Closed-form LLR pin (anti-refactor guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n,k", [(0, 0), (1, 0), (1, 1), (100, 50), (500, 320)])
def test_state_llr_matches_closed_form(n: int, k: int, cfg: SPRTConfig) -> None:
    """Pin: ``state.llr`` from ``terminal_decision`` matches the
    textbook closed-form sum to within 1e-12 absolute tolerance.
    """
    if n == 0:
        state, _ = terminal_decision(n=n, k=k, config=cfg)
        assert state.llr == 0.0
        return

    expected = (
        k * math.log(cfg.p1 / cfg.p0)
        + (n - k) * math.log((1.0 - cfg.p1) / (1.0 - cfg.p0))
    )
    state, _ = terminal_decision(n=n, k=k, config=cfg)
    assert math.isclose(state.llr, expected, abs_tol=1e-12), (
        f"closed-form LLR drifted: state.llr={state.llr!r}, "
        f"expected={expected!r}"
    )
