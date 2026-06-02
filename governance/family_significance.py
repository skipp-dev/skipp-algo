"""EV-14 / C4 — per-family significance via block bootstrap + Benjamini-Hochberg.

Honest scope. This module turns a family's *forward-test return series* into a
one-sided significance ``p``-value for the only hypothesis the series can
falsify on its own — ``H0: mean net return <= 0`` versus ``H1: mean > 0`` — and
then controls the false discovery rate across the family of such tests with the
Benjamini-Hochberg step-up procedure. It fills the gate's ``fdr_pvalue`` slot
from the SAME return series the PSR/MinTRL producer already consumes. No
fabricated probabilities, no new upstream data.

Two deliberate statistical choices:

1. **Serial correlation.** Per-trade returns overlap over the label horizon, so
   an i.i.d. permutation/bootstrap would understate the p-value (anti-
   conservative). We resample with the Politis-Romano stationary block bootstrap
   (the C3.1 primitive in :mod:`smc_core.inference.bootstrap`) using an expected
   block length tied to the family's outcome horizon.

2. **FDR, not per-test alpha.** A single family in isolation has no false-
   discovery rate — FDR is intrinsically a multiple-testing quantity. The raw
   per-family p-value is therefore only meaningful once adjusted across the
   evaluated families, which is why the gate's ``fdr_pvalue`` is filled at the
   bundle level (see :func:`scripts.build_family_metrics.build_bundle`), never
   per family.

Roadmap pointer: Edge-Validation Roadmap, Phase 2 / story EV-14 (C4).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

# C3.1 consolidated, tested resampling primitives. Importing the private
# helpers keeps a single resampler implementation in the codebase rather than
# forking the Politis-Romano loop here.
from smc_core.inference.bootstrap import _iid_resample, _stationary_resample

__all__ = [
    "benjamini_hochberg_qvalues",
    "block_bootstrap_pvalue",
    "family_fdr_qvalues",
]

# Minimum observations for a meaningful bootstrap location test. The metrics
# producer enforces a much larger floor (MIN_OBSERVATIONS_FOR_PSR); this is only
# the hard mathematical minimum below which the test is degenerate.
_MIN_OBSERVATIONS = 2


def block_bootstrap_pvalue(
    returns: Sequence[float],
    *,
    block_length: int,
    B: int = 2000,
    seed: int = 0,
) -> float:
    """One-sided stationary-block bootstrap p-value for ``mean(returns) > 0``.

    Implements the textbook bootstrap location test: recenter the sample to the
    H0 boundary (mean zero), draw ``B`` block-bootstrap resamples of the
    recentered series, and measure how often a resampled mean is at least as
    large as the observed mean. The Phipson-Smyth ``(+1)/(B+1)`` correction
    keeps the p-value strictly positive and conservatively calibrated.

    Parameters
    ----------
    returns:
        1-D forward-test return series (already net of cost).
    block_length:
        Expected block length for the stationary bootstrap. Clamped to
        ``[1, n-1]``; ``1`` collapses to the i.i.d. bootstrap. Tie this to the
        label/outcome horizon so overlapping returns are resampled in blocks.
    B:
        Number of bootstrap resamples.
    seed:
        Determinism pin.

    Returns the one-sided p-value in ``(0, 1]``. A small value is evidence the
    mean net return is positive; ``mean <= 0`` yields a p-value ``>= ~0.5``.
    """
    arr = np.asarray(returns, dtype=np.float64).ravel()
    n = arr.size
    if n < _MIN_OBSERVATIONS:
        raise ValueError(f"need at least {_MIN_OBSERVATIONS} returns, got {n}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("returns must contain only finite values")
    if B <= 0:
        raise ValueError(f"B must be positive, got {B}")
    if block_length < 1:
        raise ValueError(f"block_length must be >= 1, got {block_length}")

    bl = min(int(block_length), n - 1)
    observed = float(arr.mean())
    # Recenter to the H0 boundary (mean exactly zero) so the resampled means
    # form the null distribution of the location statistic.
    centered = arr - observed

    rng = np.random.default_rng(seed)
    resamples = (
        _iid_resample(centered, B, rng)
        if bl <= 1
        else _stationary_resample(centered, B, bl, rng)
    )
    boot_means = resamples.mean(axis=1)
    # Phipson-Smyth: (#{null >= observed} + 1) / (B + 1). The tiny epsilon
    # tolerates floating-point equality at the boundary (observed ~ 0).
    extreme = int(np.sum(boot_means >= observed - 1e-15))
    return (extreme + 1) / (B + 1)


def benjamini_hochberg_qvalues(pvalues: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg (1995) step-up adjusted q-values, in input order.

    Each adjusted value is ``min over k>=rank of p_(k) * m / k`` clipped to
    ``[0, 1]`` — the standard monotone BH q-value. Ties and unsorted inputs are
    handled; an empty input returns an empty list.
    """
    m = len(pvalues)
    if m == 0:
        return []
    sanitized = [float(p) for p in pvalues]
    if any(not 0.0 <= p <= 1.0 for p in sanitized):
        raise ValueError("p-values must lie in [0, 1]")

    order = sorted(range(m), key=lambda i: sanitized[i])
    adj_sorted = [0.0] * m
    running_min = 1.0
    # Walk from the largest p-value (rank m) down to rank 1, enforcing the
    # non-decreasing-in-rank monotonicity BH requires.
    for rank in range(m, 0, -1):
        sorted_idx = rank - 1
        adj = sanitized[order[sorted_idx]] * m / rank
        running_min = min(running_min, adj)
        adj_sorted[sorted_idx] = min(running_min, 1.0)

    out = [0.0] * m
    for sorted_idx, orig_idx in enumerate(order):
        out[orig_idx] = adj_sorted[sorted_idx]
    return out


def family_fdr_qvalues(raw_pvalues: Mapping[str, float]) -> dict[str, float]:
    """Map a ``{family: raw_pvalue}`` mapping to BH-adjusted ``{family: q}``.

    The adjustment is taken across exactly the families present, so the false
    discovery rate is controlled over the set of edges actually evaluated in the
    run — not a fixed universe.
    """
    families = list(raw_pvalues)
    qvalues = benjamini_hochberg_qvalues([raw_pvalues[f] for f in families])
    return dict(zip(families, qvalues, strict=True))
