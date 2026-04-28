"""Strategy-level permutation tests for OOS trade returns.

Sprint C4 / T2 — see ``docs/SPRINT_PLAN_C4_PERMUTATION_TEST_2026-04-26.md``.

This module ships two schemas of trade-return permutation:

* **Schema A (outcome_sign)** — independent per-trade sign flips. Cheap,
  needs no OHLCV provider and no entry-time list. Caveat: under skewed
  P&L distributions the Schema-A null PF distribution has a non-unit
  expected value, so the *PF* p-value is mis-calibrated. Sharpe-side
  Schema A is unbiased under the i.i.d.-sign null.
* **Schema B (block_outcome_sign)** — block sign flips that preserve
  serial correlation in the trade-return stream. Equivalent to a
  moving-block adaptation of the Schema-A null and conceptually
  aligned with :func:`smc_core.inference.permutation.block_permutation_test`
  (which is the two-sample variant for treatment-vs-control trade
  arms; this module's API is single-arm). Use Schema B for live
  Phase-B / Track-Record gating on intraday strategies where trade
  outcomes carry autocorrelation.

Schema B was deferred in the initial C4 PR (entry-time permutation
requires OHLCV access). The 2026-04-27 deep review surfaced that the
live pipeline was still running on Schema A; this revision makes
Schema B a first-class top-level path while keeping Schema A as a
backwards-compatible API special case.

Reuse:
- ``scripts.run_ab_comparison.benjamini_hochberg`` for the multi-setup
  FDR aggregation in :func:`aggregate_permutation_results`.
- Phipson-Smyth ``(r + 1) / (B + 1)`` correction lifted from
  ``scripts/run_ab_comparison.py:_permutation_p_delta_metric``.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from scripts.bootstrap_methods import (
    DEFAULT_B,
    DEFAULT_SEED,
    MIN_EVENTS_FOR_BOOTSTRAP,
)

PermutationSchema = Literal["outcome_sign", "block_outcome_sign"]

# Default block size for Schema B. ``5`` matches the typical
# autocorrelation-decay length observed for daily-bar SMC trade returns
# on liquid futures (per the C3 bootstrap calibration). Callers should
# override per-strategy when a measured autocorrelation length is
# available; the C8 live-incubation runbook documents how to estimate it.
DEFAULT_BLOCK_SIZE = 5


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


def _permute_outcome_sign_block(
    returns: np.ndarray, *, B: int, seed: int, block_size: int
) -> np.ndarray:
    """Schema B: flip sign in contiguous blocks of length ``block_size``.

    Each block draws an independent ±1 multiplier; signs *within* a
    block are tied. ``block_size == 1`` reduces to Schema A exactly
    (same per-element distribution). Trailing partial block is handled
    by repeating the final draw.

    The block-sign-flip null preserves the within-block autocorrelation
    of the original return stream, which the per-trade Schema A
    destroys. This matches the moving-block permutation philosophy
    used by :func:`smc_core.inference.permutation.block_permutation_test`
    in the two-sample setting.
    """
    if block_size < 1:
        raise ValueError(f"block_size must be >= 1, got {block_size}")
    n = returns.size
    rng = np.random.default_rng(seed)
    n_blocks = (n + block_size - 1) // block_size
    block_signs = rng.choice(np.array([-1.0, 1.0]), size=(B, n_blocks))
    # Expand block-level signs to per-element signs via repeat, then trim.
    signs = np.repeat(block_signs, block_size, axis=1)[:, :n]
    return returns[None, :] * signs


def _select_permuter(
    schema: PermutationSchema, *, block_size: int
):
    """Dispatch to the chosen permutation engine.

    Schema B silently falls back to Schema A when ``block_size <= 1``
    so callers can pass ``block_size=1`` to disable blocking without
    branching.
    """
    if schema == "outcome_sign":
        return lambda arr, *, B, seed: _permute_outcome_sign(arr, B=B, seed=seed)
    if schema == "block_outcome_sign":
        if block_size <= 1:
            return lambda arr, *, B, seed: _permute_outcome_sign(arr, B=B, seed=seed)
        return lambda arr, *, B, seed: _permute_outcome_sign_block(
            arr, B=B, seed=seed, block_size=block_size,
        )
    raise ValueError(
        f"schema {schema!r} not supported; use 'outcome_sign' (Schema A) "
        "or 'block_outcome_sign' (Schema B)"
    )


def permutation_test_sharpe(
    returns: np.ndarray,
    *,
    schema: PermutationSchema = "outcome_sign",
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
    freq: int = 252,
    min_events: int = MIN_EVENTS_FOR_BOOTSTRAP,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> dict[str, object]:
    """Permutation test for Sharpe ratio under Schema A or B.

    H0 (Schema A): trade-return signs are exchangeable; the strategy
    has no edge in choosing winners over losers.
    H0 (Schema B): trade-return signs are exchangeable in contiguous
    blocks of ``block_size``; the strategy has no autocorrelated edge.
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
    permuter = _select_permuter(schema, block_size=block_size)

    sqrt_freq = float(np.sqrt(freq))
    sr_obs_periodic = _sharpe_periodic(arr)
    sr_obs = sr_obs_periodic * sqrt_freq

    permuted = permuter(arr, B=B, seed=seed)
    mu = permuted.mean(axis=1)
    sd = permuted.std(axis=1, ddof=1)
    sd_safe = np.where(sd == 0.0, np.nan, sd)
    null_sr = (mu / sd_safe) * sqrt_freq

    p_one = _permutation_p_value(sr_obs, null_sr, side="one_sided")
    p_two = _permutation_p_value(sr_obs, null_sr, side="two_sided")

    out: dict[str, object] = {
        "metric": "sharpe",
        "schema": schema,
        "value": float(sr_obs),
        "p_value_one_sided": float(p_one),
        "p_value_two_sided": float(p_two),
        "B": int(B),
        "n": int(arr.size),
        "freq": int(freq),
    }
    if schema == "block_outcome_sign":
        out["block_size"] = int(block_size)
    return out


def permutation_test_profit_factor(
    pnl: np.ndarray,
    *,
    schema: PermutationSchema = "outcome_sign",
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
    min_events: int = MIN_EVENTS_FOR_BOOTSTRAP,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> dict[str, object]:
    """Permutation test for profit factor (Schema A or B).

    Note: under skewed P&L distributions both Schema A and Schema B
    null PF distributions have a non-unit expected value (the mean of
    a ratio of sign-flipped sums is not 1). Block sign-flips reduce
    the bias for autocorrelated streams but do not eliminate it.
    Treat the PF p-value as a directional sanity check.
    """

    arr = np.asarray(pnl, dtype=np.float64).ravel()
    if arr.size < min_events:
        return {
            "metric": "profit_factor",
            "schema": schema,
            "skipped_reason": "insufficient_trades",
            "n": int(arr.size),
            "min_events": int(min_events),
        }
    permuter = _select_permuter(schema, block_size=block_size)

    pf_obs = _profit_factor(arr)
    permuted = permuter(arr, B=B, seed=seed)
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

    p_one = _permutation_p_value(pf_obs, null_pf, side="one_sided")

    out: dict[str, object] = {
        "metric": "profit_factor",
        "schema": schema,
        "value": float(pf_obs),
        "p_value_one_sided": float(p_one),
        "B": int(B),
        "n": int(arr.size),
        # C4 deep-review caveat (also in the docstring above): the
        # null-PF distribution has a non-unit expected value under
        # skewed P&L for both Schema A and Schema B, so this p-value
        # is *mis-calibrated as a PF-edge test*. Mark every emission
        # so dashboard / public report consumers can render the
        # warning explicitly instead of relying on readers to find
        # the docstring.
        "caveat": "null_miscal_under_skew",
        "caveat_replacement": "prefer_sharpe_or_two_sample_block_permutation",
    }
    if schema == "block_outcome_sign":
        out["block_size"] = int(block_size)
    return out


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
    "DEFAULT_BLOCK_SIZE",
    "PermutationSchema",
    "aggregate_permutation_results",
    "permutation_test_profit_factor",
    "permutation_test_sharpe",
]
