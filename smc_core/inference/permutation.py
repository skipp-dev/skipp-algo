"""Sprint C4.1 — Block permutation test for serially-correlated samples.

Classical iid label-permutation breaks autocorrelation in the underlying
return stream and therefore tends to under-estimate p-values for
strategies tested at high frequency. This module ships a generic
two-sample permutation test that supports a ``block_size`` parameter:
when ``block_size > 1``, treatment/control labels are shuffled in
contiguous blocks rather than per-observation, preserving local
autocorrelation under the null.

API surface::

    from smc_core.inference.permutation import block_permutation_test

    p, observed, null = block_permutation_test(
        treatment=t_arr,
        control=c_arr,
        statistic=lambda t, c: float(t.mean() - c.mean()),
        block_size=5,
        B=1000,
        seed=0,
        alternative="two-sided",
    )

The returned p-value uses the Phipson-Smyth ``(r + 1) / (B + 1)``
correction so it is never zero. ``block_size=1`` reproduces the iid
permutation test exactly (verified by smoke test).

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c41
"""
from __future__ import annotations

from typing import Callable, Literal

import numpy as np

Alternative = Literal["two-sided", "greater", "less"]


def _validate(name: str, arr: np.ndarray) -> np.ndarray:
    out = np.asarray(arr, dtype=np.float64).ravel()
    if out.size == 0:
        raise ValueError(f"{name} must be non-empty")
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{name} must contain only finite values")
    return out


def _block_indices(n: int, block_size: int, rng: np.random.Generator) -> np.ndarray:
    """Return a permutation of ``range(n)`` that shuffles contiguous blocks.

    The block grid is fixed (``[0:bs], [bs:2*bs], ...``); only the order
    of the blocks is randomised. This is the classical "moving-block
    permutation" used in time-series resampling.
    """
    if block_size <= 1:
        return rng.permutation(n)
    block_starts = np.arange(0, n, block_size)
    perm = rng.permutation(len(block_starts))
    out = np.empty(n, dtype=np.int64)
    cursor = 0
    for b in perm:
        s = int(block_starts[b])
        e = min(s + block_size, n)
        seg = e - s
        out[cursor : cursor + seg] = np.arange(s, e)
        cursor += seg
    assert cursor == n
    return out


def block_permutation_test(
    *,
    treatment: np.ndarray,
    control: np.ndarray,
    statistic: Callable[[np.ndarray, np.ndarray], float],
    block_size: int = 1,
    B: int = 1000,
    seed: int = 0,
    alternative: Alternative = "two-sided",
) -> tuple[float, float, np.ndarray]:
    """Two-sample permutation test with optional block resampling.

    Returns ``(p_value, observed, null_distribution)``.

    Parameters
    ----------
    treatment, control:
        1-D arrays. The pooled sample is ``concat(treatment, control)``.
    statistic:
        ``(treatment_arr, control_arr) -> float``. Larger magnitude
        means more extreme. ``alternative`` controls the tail.
    block_size:
        ``1`` -> classical iid permutation; ``>1`` -> moving-block.
    B:
        Number of permutations.
    seed:
        Determinism.
    alternative:
        ``"two-sided"`` (default), ``"greater"``, or ``"less"``.
    """
    if block_size < 1:
        raise ValueError(f"block_size must be >= 1, got {block_size}")
    if B <= 0:
        raise ValueError(f"B must be positive, got {B}")
    t = _validate("treatment", treatment)
    c = _validate("control", control)
    n_t = t.size
    pooled = np.concatenate([t, c])
    n = pooled.size

    observed = float(statistic(t, c))
    rng = np.random.default_rng(seed)
    null = np.empty(B, dtype=np.float64)
    for b in range(B):
        idx = _block_indices(n, block_size, rng)
        permuted = pooled[idx]
        t_b = permuted[:n_t]
        c_b = permuted[n_t:]
        null[b] = float(statistic(t_b, c_b))

    if alternative == "two-sided":
        # Phipson-Smyth: (#{|null| >= |observed|} + 1) / (B + 1)
        extreme = int(np.sum(np.abs(null) >= abs(observed) - 1e-12))
    elif alternative == "greater":
        extreme = int(np.sum(null >= observed - 1e-12))
    elif alternative == "less":
        extreme = int(np.sum(null <= observed + 1e-12))
    else:  # pragma: no cover - guarded by Literal
        raise ValueError(f"unknown alternative: {alternative}")
    p_value = (extreme + 1) / (B + 1)
    return float(p_value), observed, null


__all__ = ["Alternative", "block_permutation_test"]
