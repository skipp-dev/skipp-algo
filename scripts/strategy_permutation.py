"""Strategy-level permutation tests for OOS trade returns.

Sprint C4 / T2 — see ``docs/SPRINT_PLAN_C4_PERMUTATION_TEST_2026-04-26.md``.

This first cut implements **Schema A** (outcome-sign permutation): the
null hypothesis says "the trade-return signs are exchangeable", i.e. a
random sign-flip of each trade should produce the same Sharpe-like
statistic in expectation. Schema A needs no OHLCV provider and no
entry-time list — it can run as soon as the OOS trade-return list from
C2 is available, and it provides a cheap sanity check that the strategy
is not producing positive Sharpe by chance alone.

Schema B (entry-time permutation, the rigorous test) needs OHLCV access
and is deferred to a follow-up PR; the dispatcher leaves room for it.

Reuse:
- ``scripts.run_ab_comparison.benjamini_hochberg`` for the multi-setup
  FDR aggregation in :func:`aggregate_permutation_results`.
- Phipson-Smyth ``(r + 1) / (B + 1)`` correction lifted from
  ``scripts/run_ab_comparison.py:_permutation_p_delta_metric``.

Caveats:
- Schema-A profit-factor permutations have a non-unit expected null
  mean under skewed P&L distributions. The PF p-value reported by
  :func:`permutation_test_profit_factor` is therefore mis-calibrated
  and should be interpreted as a sanity check only. Schema B (entry-time
  permutation) lands the calibrated version.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from scripts.bootstrap_methods import (
    DEFAULT_B,
    DEFAULT_SEED,
    MIN_EVENTS_FOR_BOOTSTRAP,
)

PermutationSchema = Literal["outcome_sign"]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _sharpe_periodic(arr: np.ndarray) -> float:
    sd = float(arr.std(ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(arr.mean()) / sd


def _profit_factor(arr: np.ndarray) -> float:
    pos = float(arr[arr > 0].sum())
    neg = -float(arr[arr < 0].sum())
    if neg == 0.0:
        return float("inf") if pos > 0 else float("nan")
    return pos / neg


# ---------------------------------------------------------------------------
# Permutation core
# ---------------------------------------------------------------------------


def _permutation_p_value(
    observed: float, null_dist: np.ndarray, *, side: Literal["one_sided", "two_sided"]
) -> float:
    """Phipson-Smyth-corrected p-value: ``(r + 1) / (B + 1)``.

    Parameters
    ----------
    observed:
        Observed test statistic.
    null_dist:
        Bootstrap/permutation null distribution.
    side:
        ``"one_sided"`` tests "observed > null" (e.g. Sharpe > 0).
        ``"two_sided"`` tests ``|observed - 0| > |null - 0|``.
    """

    null_finite = null_dist[np.isfinite(null_dist)]
    B = int(null_finite.size)
    if B == 0:
        return float("nan")
    if side == "one_sided":
        r = int((null_finite >= observed).sum())
    else:
        r = int((np.abs(null_finite) >= abs(observed)).sum())
    return (r + 1.0) / (B + 1.0)


def _permute_outcome_sign(
    returns: np.ndarray, *, B: int, seed: int
) -> np.ndarray:
    """Schema A: independently flip the sign of each trade with p=0.5.

    Returns a ``(B, n)`` matrix of sign-flipped resamples.
    """

    rng = np.random.default_rng(seed)
    # Random ±1 mask, fully vectorized.
    signs = rng.choice(np.array([-1.0, 1.0]), size=(B, returns.size))
    return returns[None, :] * signs


def permutation_test_sharpe(
    returns: np.ndarray,
    *,
    schema: PermutationSchema = "outcome_sign",
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
    freq: int = 252,
    min_events: int = MIN_EVENTS_FOR_BOOTSTRAP,
) -> dict[str, object]:
    """Permutation test for Sharpe ratio under Schema A.

    H0 (Schema A): trade-return signs are exchangeable; the strategy
    has no edge in choosing winners over losers.
    """

    arr = np.asarray(returns, dtype=np.float64).ravel()
    if arr.size < min_events:
        return {
            "metric": "sharpe",
            "schema": schema,
            "skipped_reason": "insufficient_trades",
            "n": int(arr.size),
            "min_events": int(min_events),
        }
    if schema != "outcome_sign":
        raise ValueError(
            f"schema {schema!r} not implemented in this PR; only 'outcome_sign' "
            "(Schema A) is available. Schema B (entry_time) lands in a follow-up."
        )

    sqrt_freq = float(np.sqrt(freq))
    sr_obs_periodic = _sharpe_periodic(arr)
    sr_obs = sr_obs_periodic * sqrt_freq

    permuted = _permute_outcome_sign(arr, B=B, seed=seed)
    mu = permuted.mean(axis=1)
    sd = permuted.std(axis=1, ddof=1)
    sd_safe = np.where(sd == 0.0, np.nan, sd)
    null_sr = (mu / sd_safe) * sqrt_freq

    p_one = _permutation_p_value(sr_obs, null_sr, side="one_sided")
    p_two = _permutation_p_value(sr_obs, null_sr, side="two_sided")

    return {
        "metric": "sharpe",
        "schema": schema,
        "value": float(sr_obs),
        "p_value_one_sided": float(p_one),
        "p_value_two_sided": float(p_two),
        "B": int(B),
        "n": int(arr.size),
        "freq": int(freq),
    }


def permutation_test_profit_factor(
    pnl: np.ndarray,
    *,
    schema: PermutationSchema = "outcome_sign",
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
    min_events: int = MIN_EVENTS_FOR_BOOTSTRAP,
) -> dict[str, object]:
    """Permutation test for profit factor (Schema A only)."""

    arr = np.asarray(pnl, dtype=np.float64).ravel()
    if arr.size < min_events:
        return {
            "metric": "profit_factor",
            "schema": schema,
            "skipped_reason": "insufficient_trades",
            "n": int(arr.size),
            "min_events": int(min_events),
        }
    if schema != "outcome_sign":
        raise ValueError(f"schema {schema!r} not implemented; only 'outcome_sign' available")

    pf_obs = _profit_factor(arr)
    permuted = _permute_outcome_sign(arr, B=B, seed=seed)
    pos = np.where(permuted > 0, permuted, 0.0).sum(axis=1)
    neg = -np.where(permuted < 0, permuted, 0.0).sum(axis=1)
    # Compute pos/neg only where neg is *strictly* greater than eps
    # (mask: ``neg > eps``); ``np.where(neg > 0, pos / np.maximum(neg, 1e-12), np.nan)``
    # would still evaluate the division for every element first (creating
    # extreme intermediate values) and the ``np.maximum`` floor would
    # silently distort the statistic for very small ``neg``. ``np.divide``
    # with ``where=`` skips the division entirely outside the mask.
    eps = 1e-12
    null_pf = np.full(neg.shape, np.nan, dtype=np.float64)
    np.divide(pos, neg, out=null_pf, where=neg > eps)

    # For PF, "edge" means observed > 1.0 vs null around 1.0; we still
    # report Phipson-Smyth p-values relative to the null distribution.
    # See module docstring "Caveats" — Schema-A PF p-values are
    # mis-calibrated under skewed P&L; use Schema B for the calibrated
    # version once available.
    p_one = _permutation_p_value(pf_obs, null_pf, side="one_sided")

    return {
        "metric": "profit_factor",
        "schema": schema,
        "value": float(pf_obs),
        "p_value_one_sided": float(p_one),
        "B": int(B),
        "n": int(arr.size),
        # C4 deep-review caveat (also in the docstring above): the
        # Schema-A null-PF distribution has a non-unit expected value
        # under skewed P&L, so this p-value is *mis-calibrated as a
        # PF-edge test*. Mark every emission so dashboard / public
        # report consumers can render the warning explicitly instead of
        # relying on readers to find the docstring.
        "caveat": "schema_a_null_miscal_under_skew",
        "caveat_replacement": "schema_b_entry_time_permutation_pending",
    }


# ---------------------------------------------------------------------------
# Multi-setup FDR aggregation (T4)
# ---------------------------------------------------------------------------


def aggregate_permutation_results(
    setup_results: dict[str, dict[str, object]],
    *,
    q: float = 0.10,
    p_field: str = "p_value_one_sided",
) -> dict[str, object]:
    """Apply BH-FDR across multiple setup-typed permutation results.

    Parameters
    ----------
    setup_results:
        Mapping ``setup_name -> permutation_test_*(...)`` result dict.
        Setups with ``skipped_reason`` are excluded from the FDR pool.
    q:
        BH false-discovery-rate level. 0.10 is the plan default
        (slightly less strict than the classical 0.05 for early-stage
        Track-Record gating).
    p_field:
        Which p-value field to feed into BH. Defaults to
        ``"p_value_one_sided"`` (the H1 "Sharpe > 0" case).

    Returns
    -------
    dict
        Per-setup augmented results plus an aggregate block:
        ``{"per_setup": {...}, "aggregate": {"fdr_q": q, "n_tested": ...,
        "n_significant": ...}}``.
    """

    # Lazy import — keep this module light when only the test helpers
    # are used.
    from scripts.run_ab_comparison import benjamini_hochberg

    eligible = {
        name: res for name, res in setup_results.items() if "skipped_reason" not in res
    }
    if not eligible:
        return {
            "per_setup": dict(setup_results),
            "aggregate": {
                "fdr_q": float(q),
                "n_tested": 0,
                "n_significant": 0,
                "skipped_reason": "no_eligible_setups",
            },
        }

    names = list(eligible.keys())
    pvals = [float(eligible[n][p_field]) for n in names]
    bh = benjamini_hochberg(pvals, q=q)

    per_setup: dict[str, dict[str, object]] = {}
    for name, res in setup_results.items():
        per_setup[name] = dict(res)
        if name in eligible:
            idx = names.index(name)
            per_setup[name]["bh_adjusted_p"] = float(bh["adjusted"][idx])
            per_setup[name]["bh_rejects_h0"] = bool(bh["rejected"][idx])
            per_setup[name]["fdr_q"] = float(q)

    n_significant = int(sum(per_setup[n].get("bh_rejects_h0", False) for n in eligible))
    return {
        "per_setup": per_setup,
        "aggregate": {
            "fdr_q": float(q),
            "n_tested": int(len(eligible)),
            "n_significant": n_significant,
        },
    }


__all__ = [
    "permutation_test_sharpe",
    "permutation_test_profit_factor",
    "aggregate_permutation_results",
]
