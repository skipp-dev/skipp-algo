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
    if cursor != n:  # pragma: no cover - defensive: impossible by construction
        raise RuntimeError(
            f"_block_indices internal error: cursor={cursor} != n={n}"
        )
    return out


def _block_aligned_split(
    permuted: np.ndarray, n_t: int, block_size: int
) -> tuple[np.ndarray, np.ndarray]:
    """Split a block-permuted index/value array into ``(treatment, control)``
    on the closest block boundary to ``n_t``.

    The C-sprint deep-review identified that the previous ``permuted[:n_t]``
    split could cut the last treatment block mid-way whenever
    ``n_t % block_size != 0``, breaking the autocorrelation-preserving
    contract of moving-block permutation under H₀. We now round the
    treatment side to a whole-block boundary so every block ends up
    entirely in one arm.

    Boundary policy (post Copilot pass-3 fix):
    * For ``n_t`` already inside ``[block_size, n - block_size]`` the
      snapped size differs from the original ``n_t`` by at most
      ``block_size // 2`` samples — negligible relative to typical ``n``.
    * The caller (:func:`block_permutation_test`) validates upfront
      that both arms span at least one full block when
      ``block_size > 1``, so the clamp branch is unreachable in
      practice; it remains as a defensive floor.
    * For ``block_size == 1`` the split is exactly at ``n_t`` (no
      behavioural change vs. the iid case).
    """
    if block_size <= 1:
        return permuted[:n_t], permuted[n_t:]
    n = permuted.size
    snapped = int(round(n_t / block_size)) * block_size
    snapped = max(block_size, min(snapped, n - block_size))
    return permuted[:snapped], permuted[snapped:]


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
    if block_size >= n:
        raise ValueError(
            f"block_size must be smaller than pooled sample size ({n}), "
            f"got {block_size}"
        )
    # Copilot pass-3 fix: when ``block_size > 1`` the snapped split rule
    # in :func:`_block_aligned_split` requires that both arms span at
    # least one full block. Reject inputs that don't, so the snapped
    # group sizes never deviate from ``n_t`` by more than
    # ``block_size // 2`` (which the docstring promises).
    if block_size > 1 and (n_t < block_size or (n - n_t) < block_size):
        raise ValueError(
            f"block_size > 1 requires both arms to span at least one full "
            f"block: n_t={n_t}, n_c={n - n_t}, block_size={block_size}"
        )

    # Copilot pass-3 fix (CRITICAL): the null draws use a snapped split
    # to keep blocks intact under H₀. Both ``observed`` and every null
    # draw must use the *same* group sizes, otherwise the test compares
    # statistics with different sample-size sampling distributions and
    # the p-value is miscalibrated. We therefore:
    #   1. Compute the canonical snapped boundary once.
    #   2. Trim ``treatment`` and ``control`` to ``snapped`` and
    #      ``n - snapped`` samples (so observed stays the genuine
    #      treatment-vs-control statistic, never mixing labels).
    #   3. Repool from the trimmed arms so null draws operate on the
    #      same effective ``n`` and inherit the aligned ``n_t``.
    if block_size > 1:
        # Trim each arm independently to a multiple of ``block_size``.
        # This guarantees:
        #  (a) the snapped n_t (= len(t)) is a multiple of block_size,
        #      so the null-draw split is exact and never cuts blocks,
        #  (b) ``observed`` and every null draw evaluate the statistic
        #      on identical group sizes (Copilot pass-3 CRITICAL fix),
        #  (c) the snap deviates from the original ``n_t`` / ``n_c``
        #      by at most ``block_size - 1`` samples — well within the
        #      "negligible" budget the docstring promises.
        n_t_trim = (t.size // block_size) * block_size
        n_c_trim = (c.size // block_size) * block_size
        if n_t_trim == 0 or n_c_trim == 0:
            # Already rejected above by the explicit-block-span guard,
            # but defensive in case future callers relax that.
            raise ValueError(
                f"block_size > 1 requires both arms to span at least one "
                f"full block: n_t={t.size}, n_c={c.size}, "
                f"block_size={block_size}"
            )
        if n_t_trim != t.size:
            t = t[:n_t_trim]
        if n_c_trim != c.size:
            c = c[:n_c_trim]
        n_t = t.size
        pooled = np.concatenate([t, c])
        n = pooled.size

    rng = np.random.default_rng(seed)
    observed = float(statistic(t, c))
    null = np.empty(B, dtype=np.float64)
    for b in range(B):
        idx = _block_indices(n, block_size, rng)
        permuted = pooled[idx]
        # With the per-arm trim above, ``n_t`` is now an exact multiple
        # of ``block_size`` so the split is exact and ``observed`` and
        # every null draw share the same group sizes.
        t_b, c_b = _block_aligned_split(permuted, n_t, block_size)
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
