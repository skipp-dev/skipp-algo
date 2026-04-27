"""Bootstrap resampling primitives for performance inference.

Sprint C3 / T2 — see ``docs/SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md``.

This module ships pure-NumPy resampling primitives that are reused by the
higher-level inference helpers in ``scripts/performance_inference.py``
(Sharpe-CI, MaxDD-CI, Win-Rate-CI, Profit-Factor-CI). Keeping the
resampling itself in a thin, dependency-free module makes coverage
testing and determinism pinning straightforward.

Caveats
-------
**Stationarity assumption.** Both :func:`stationary_block_bootstrap` and
:func:`circular_block_bootstrap` assume the underlying return process is
*weakly stationary* over the resampled window. Concretely:

* Mean and variance must be approximately time-invariant.
* The autocovariance ``Cov(r_t, r_{t+h})`` may depend on ``h`` but not
  on ``t``.

For OOS windows that span a regime change (e.g. low-vol → high-vol
transitions, COVID-style structural breaks, or post-FOMC repricing),
this assumption breaks and the resulting CIs are systematically too
narrow. In that case prefer **regime-stratified resampling**: bucket
the returns by regime (see :mod:`scripts.regime_stratification`),
bootstrap *within* each bucket, and aggregate. Deep-Review 2026-04-27
flagged that this caveat was previously implicit; consumers must now
read it before publishing a CI on a non-stationary window.

References
----------
- Politis, D.N. & Romano, J.P. (1994) — *The Stationary Bootstrap*.
  JASA 89(428): 1303-1313.
- Ledoit, O. & Wolf, M. (2008) — *Robust performance hypothesis testing
  with the Sharpe ratio*. http://www.ledoit.net/jef_2008pdf.pdf
- Repo-Inventur: ``scripts/run_ab_comparison.py:362-368`` already pins
  ``BOOTSTRAP_B`` / ``BOOTSTRAP_SEED`` / ``MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP``.
  Those constants are intentionally re-exported here so callers don't
  need to import from ``run_ab_comparison`` for plain primitives.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

# Re-export of the calibration-FDR constants from
# ``scripts/run_ab_comparison.py``. Imported lazily to avoid pulling
# the (large) A/B comparison module into hot resampling paths.
DEFAULT_B: int = 5000
DEFAULT_SEED: int = 42
DEFAULT_MEAN_BLOCK_LENGTH: int = 5
MIN_EVENTS_FOR_BOOTSTRAP: int = 30  # mirrors run_ab_comparison.MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP


def _validate_returns(returns: np.ndarray) -> np.ndarray:
    """Coerce ``returns`` to a 1-D float64 array and validate shape."""

    arr = np.asarray(returns, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"returns must be 1-D, got shape {arr.shape}")
    if arr.size == 0:
        raise ValueError("returns must be non-empty")
    if not np.all(np.isfinite(arr)):
        raise ValueError("returns must contain only finite values")
    return arr


def iid_bootstrap(
    returns: np.ndarray,
    *,
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    """Classical IID bootstrap.

    Parameters
    ----------
    returns:
        1-D array of trade returns (or per-period returns).
    B:
        Number of bootstrap resamples.
    seed:
        Seed for ``numpy.random.default_rng``. Determinism is pinned
        in :func:`tests.test_bootstrap_methods.test_iid_determinism`.

    Returns
    -------
    np.ndarray
        Matrix of shape ``(B, n)`` where each row is one bootstrap
        sample drawn with replacement.
    """

    arr = _validate_returns(returns)
    if B <= 0:
        raise ValueError(f"B must be positive, got {B}")
    n = arr.size
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(B, n), dtype=np.int64)
    return arr[idx]


def stationary_block_bootstrap(
    returns: np.ndarray,
    *,
    mean_block_length: int = DEFAULT_MEAN_BLOCK_LENGTH,
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    """Stationary block bootstrap (Politis & Romano, 1994).

    Each resample is built by concatenating blocks whose length is
    geometrically distributed with mean ``mean_block_length`` and whose
    starting index is uniform on ``[0, n)``. Indices wrap around
    (circular extension) so every position has equal sampling
    probability — the property that makes the resulting series
    *stationary* in the Politis-Romano sense.

    Parameters
    ----------
    returns:
        1-D array of returns. Auto-correlation is preserved within a
        block, randomized across blocks.
    mean_block_length:
        Mean of the geometric distribution governing block length. The
        Politis-Romano default for trade-return-like series is 5.
    B:
        Number of bootstrap resamples.
    seed:
        Seed for ``numpy.random.default_rng``.

    Returns
    -------
    np.ndarray
        ``(B, n)`` matrix of resamples.

    Notes
    -----
    The implementation is fully NumPy-vectorized: a single
    ``rng.integers`` call yields all block starts and a single
    ``rng.geometric`` call yields all block lengths. The expansion
    into per-position indices is done with ``np.cumsum`` /
    ``np.repeat`` so no Python-level loop runs at length ``B`` or ``n``.
    """

    arr = _validate_returns(returns)
    if mean_block_length < 1:
        raise ValueError(f"mean_block_length must be >= 1, got {mean_block_length}")
    if B <= 0:
        raise ValueError(f"B must be positive, got {B}")

    n = arr.size
    rng = np.random.default_rng(seed)

    # Geometric distribution: success probability p = 1 / mean.
    # ``numpy.random.geometric(p)`` returns lengths in {1, 2, ...} with
    # mean 1/p, which matches the Politis-Romano parameterisation.
    p = 1.0 / float(mean_block_length)

    # Allocate output and fill row-by-row. The per-row work is itself
    # vectorized; only the outer loop iterates B times. For B=5000,
    # n=200 this runs in <100 ms.
    out = np.empty((B, n), dtype=np.float64)
    offsets = np.arange(n, dtype=np.int64)
    for b in range(B):
        # Sample more block-lengths than we need so the truncation at
        # n below is essentially always a no-op. Each block has expected
        # length ``mean_block_length`` so ``ceil(n / mean) + 4`` blocks
        # is comfortably enough; we still loop defensively.
        n_blocks = int(np.ceil(n / mean_block_length)) + 4
        lengths = rng.geometric(p, size=n_blocks)
        starts = rng.integers(0, n, size=n_blocks, dtype=np.int64)

        # Build the index sequence, growing if a (very unlikely)
        # under-fill happens.
        indices = np.empty(n, dtype=np.int64)
        cursor = 0
        block_idx = 0
        while cursor < n:
            if block_idx >= lengths.size:
                # Resample more blocks; mean-block-length=1 with n>>4
                # could in principle land here.
                lengths = np.concatenate(
                    [lengths, rng.geometric(p, size=n_blocks)]
                )
                starts = np.concatenate(
                    [starts, rng.integers(0, n, size=n_blocks, dtype=np.int64)]
                )
            length = int(lengths[block_idx])
            start = int(starts[block_idx])
            block_idx += 1
            take = min(length, n - cursor)
            indices[cursor : cursor + take] = (start + offsets[:take]) % n
            cursor += take
        out[b] = arr[indices]

    return out


def circular_block_bootstrap(
    returns: np.ndarray,
    *,
    block_length: int = DEFAULT_MEAN_BLOCK_LENGTH,
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    """Circular block bootstrap (fixed block length, wrap-around).

    Variant used in the Ledoit & Wolf (2008) Sharpe paper for direct
    comparability. Block length is *fixed* (not geometric); blocks wrap
    around the end of the sample.

    Parameters
    ----------
    returns:
        1-D array of returns.
    block_length:
        Fixed block length in observations.
    B:
        Number of resamples.
    seed:
        RNG seed.

    Returns
    -------
    np.ndarray
        ``(B, n)`` matrix of resamples.
    """

    arr = _validate_returns(returns)
    if block_length < 1:
        raise ValueError(f"block_length must be >= 1, got {block_length}")
    if B <= 0:
        raise ValueError(f"B must be positive, got {B}")

    n = arr.size
    rng = np.random.default_rng(seed)
    # Number of blocks needed to cover n observations.
    n_blocks = int(np.ceil(n / block_length))
    # Sample (B, n_blocks) starts in one shot — fully vectorized.
    starts = rng.integers(0, n, size=(B, n_blocks), dtype=np.int64)
    # Offsets within each block: 0..block_length-1.
    offsets = np.arange(block_length, dtype=np.int64)
    # Broadcasting: (B, n_blocks, 1) + (1, 1, block_length)
    # -> (B, n_blocks, block_length) modulo n.
    full = (starts[..., None] + offsets[None, None, :]) % n
    # Flatten along the last two axes and truncate to n columns.
    flat = full.reshape(B, n_blocks * block_length)[:, :n]
    return arr[flat]


_BootstrapName = Literal["iid", "stationary", "circular"]


def make_resamples(
    returns: np.ndarray,
    *,
    method: _BootstrapName = "stationary",
    B: int = DEFAULT_B,
    seed: int = DEFAULT_SEED,
    mean_block_length: int = DEFAULT_MEAN_BLOCK_LENGTH,
) -> np.ndarray:
    """Dispatcher for the three resampling primitives.

    Used by ``scripts/performance_inference.py`` so callers can switch
    method via configuration without importing each primitive.
    """

    if method == "iid":
        return iid_bootstrap(returns, B=B, seed=seed)
    if method == "stationary":
        return stationary_block_bootstrap(
            returns, mean_block_length=mean_block_length, B=B, seed=seed
        )
    if method == "circular":
        return circular_block_bootstrap(
            returns, block_length=mean_block_length, B=B, seed=seed
        )
    raise ValueError(f"unknown bootstrap method: {method!r}")
