"""Regime-stratified bootstrap and permutation (Sprint C5 / T4).

Both procedures preserve the per-regime trade composition so the
resulting confidence intervals / p-values reflect the *regime mix*
the model was actually trained against.

Why a separate module
---------------------

``scripts/bootstrap_methods.py`` resamples a flat returns array; that
implicitly assumes regime composition is exchangeable. For the C5
gate we want to detect regime concentration, so we resample within
each regime bucket independently and re-stitch — i.e. a stratified
block design.

``scripts/strategy_permutation.py`` does the same for sign / label
shuffles. ``regime_stratified_permutation`` wraps it with a
within-bucket shuffle so any aggregate p-value still respects the
regime concentration test from
``scripts.regime_stratification.detect_regime_concentration``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from scripts.bootstrap_methods import make_resamples
from scripts.regime_stratification import (
    MIN_TRADES_PER_REGIME,
    stratify_trades_by_regime,
)

__all__ = [
    "RegimeStratifiedResult",
    "regime_stratified_bootstrap",
    "regime_stratified_permutation",
]

Trade = Mapping[str, Any]


class RegimeStratifiedResult(dict):
    """Lightweight typed-ish dict result.

    Keys:
        statistic_observed: the observed scalar of ``statistic_fn(pnls)``
        ci_lower, ci_upper: bootstrap CI bounds (None if not enough data)
        n_resamples: total resamples that were aggregated
        per_regime_n: {regime: n_trades}
        skipped_regimes: regimes dropped for n < MIN_TRADES_PER_REGIME
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_pnls(bucket: Sequence[Trade], pnl_col: str) -> np.ndarray:
    out = np.empty(len(bucket), dtype=np.float64)
    for i, t in enumerate(bucket):
        v = t.get(pnl_col)
        if v is None:
            raise ValueError(f"trade missing {pnl_col!r}: {t!r}")
        out[i] = float(v)
    return out


def _aggregate_pnls(
    buckets: dict[str, np.ndarray],
    weights: dict[str, float] | None,
) -> np.ndarray:
    """Concatenate per-regime arrays. Weights ignored — we keep
    per-trade granularity so the statistic_fn sees the natural
    composition. Reserved for future weighted variants."""

    del weights
    if not buckets:
        return np.empty(0, dtype=np.float64)
    return np.concatenate([buckets[k] for k in sorted(buckets)])


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def regime_stratified_bootstrap(
    trades: Sequence[Trade],
    statistic_fn: Callable[[np.ndarray], float],
    *,
    pnl_col: str = "pnl",
    regime_col: str = "regime_at_entry",
    method: str = "stationary",
    B: int = 1000,
    seed: int = 0,
    mean_block_length: int = 10,
    ci_alpha: float = 0.05,
) -> RegimeStratifiedResult:
    """Stratified bootstrap of a scalar statistic.

    For each regime with at least ``MIN_TRADES_PER_REGIME`` trades we
    draw ``B`` resamples via :func:`make_resamples`, then concatenate
    column-wise (per resample) and apply ``statistic_fn`` to each
    aggregated sample to build the bootstrap distribution.
    """

    buckets_raw = stratify_trades_by_regime(trades, regime_col=regime_col)
    per_regime_pnls: dict[str, np.ndarray] = {}
    per_regime_n: dict[str, int] = {}
    skipped: list[str] = []
    for regime, bucket in buckets_raw.items():
        per_regime_n[regime] = len(bucket)
        if len(bucket) < MIN_TRADES_PER_REGIME:
            skipped.append(regime)
            continue
        per_regime_pnls[regime] = _extract_pnls(bucket, pnl_col)

    if not per_regime_pnls:
        return RegimeStratifiedResult(
            statistic_observed=None,
            ci_lower=None,
            ci_upper=None,
            n_resamples=0,
            per_regime_n=per_regime_n,
            skipped_regimes=skipped,
        )

    observed = float(statistic_fn(_aggregate_pnls(per_regime_pnls, None)))

    # Per-regime resamples: shape (B, n_regime). Use a per-regime seed
    # offset so distinct regimes get independent draws while the whole
    # call stays reproducible from ``seed``.
    resample_matrices: dict[str, np.ndarray] = {}
    for offset, regime in enumerate(sorted(per_regime_pnls)):
        resample_matrices[regime] = make_resamples(
            per_regime_pnls[regime],
            method=method,
            B=B,
            seed=seed + offset,
            mean_block_length=mean_block_length,
        )

    # Stitch per-resample row → aggregated array → statistic.
    samples = np.empty(B, dtype=np.float64)
    for b in range(B):
        agg = np.concatenate(
            [resample_matrices[r][b] for r in sorted(resample_matrices)]
        )
        samples[b] = float(statistic_fn(agg))

    finite = samples[np.isfinite(samples)]
    if finite.size < 2:
        return RegimeStratifiedResult(
            statistic_observed=observed,
            ci_lower=None,
            ci_upper=None,
            n_resamples=int(finite.size),
            per_regime_n=per_regime_n,
            skipped_regimes=skipped,
        )

    lo = float(np.quantile(finite, ci_alpha / 2.0))
    hi = float(np.quantile(finite, 1.0 - ci_alpha / 2.0))
    return RegimeStratifiedResult(
        statistic_observed=observed,
        ci_lower=lo,
        ci_upper=hi,
        n_resamples=int(finite.size),
        per_regime_n=per_regime_n,
        skipped_regimes=skipped,
    )


# ---------------------------------------------------------------------------
# Permutation
# ---------------------------------------------------------------------------


def regime_stratified_permutation(
    trades_a: Sequence[Trade],
    trades_b: Sequence[Trade],
    statistic_fn: Callable[[np.ndarray, np.ndarray], float],
    *,
    pnl_col: str = "pnl",
    regime_col: str = "regime_at_entry",
    n_permutations: int = 1000,
    seed: int = 0,
) -> RegimeStratifiedResult:
    """Two-sample permutation that swaps labels *within* each regime.

    For every regime present in either group we pool the trades and
    randomly relabel them, preserving the per-regime n_a / n_b split.
    The resulting two-sided p-value is the fraction of permutations
    whose ``|stat|`` is at least the observed ``|stat|``.
    """

    buckets_a = stratify_trades_by_regime(trades_a, regime_col=regime_col)
    buckets_b = stratify_trades_by_regime(trades_b, regime_col=regime_col)
    all_regimes = sorted(set(buckets_a) | set(buckets_b))

    pnls_a: dict[str, np.ndarray] = {}
    pnls_b: dict[str, np.ndarray] = {}
    skipped: list[str] = []
    per_regime_n: dict[str, int] = {}

    for regime in all_regimes:
        a_bucket = buckets_a.get(regime, [])
        b_bucket = buckets_b.get(regime, [])
        per_regime_n[regime] = len(a_bucket) + len(b_bucket)
        if min(len(a_bucket), len(b_bucket)) < MIN_TRADES_PER_REGIME:
            skipped.append(regime)
            continue
        pnls_a[regime] = _extract_pnls(a_bucket, pnl_col)
        pnls_b[regime] = _extract_pnls(b_bucket, pnl_col)

    if not pnls_a:
        return RegimeStratifiedResult(
            statistic_observed=None,
            p_value=None,
            n_resamples=0,
            per_regime_n=per_regime_n,
            skipped_regimes=skipped,
        )

    a_obs = np.concatenate([pnls_a[r] for r in sorted(pnls_a)])
    b_obs = np.concatenate([pnls_b[r] for r in sorted(pnls_b)])
    observed = float(statistic_fn(a_obs, b_obs))

    rng = np.random.default_rng(seed)
    pooled = {r: np.concatenate([pnls_a[r], pnls_b[r]]) for r in pnls_a}
    sizes_a = {r: pnls_a[r].size for r in pnls_a}

    n_extreme = 0
    finite_count = 0
    for _ in range(n_permutations):
        perm_a_parts: list[np.ndarray] = []
        perm_b_parts: list[np.ndarray] = []
        for regime in sorted(pooled):
            pool = pooled[regime]
            idx = rng.permutation(pool.size)
            shuffled = pool[idx]
            na = sizes_a[regime]
            perm_a_parts.append(shuffled[:na])
            perm_b_parts.append(shuffled[na:])
        stat = float(statistic_fn(
            np.concatenate(perm_a_parts), np.concatenate(perm_b_parts)
        ))
        if not np.isfinite(stat):
            continue
        finite_count += 1
        if abs(stat) >= abs(observed):
            n_extreme += 1

    p_value = (
        (n_extreme + 1) / (finite_count + 1) if finite_count > 0 else None
    )
    return RegimeStratifiedResult(
        statistic_observed=observed,
        p_value=p_value,
        n_resamples=finite_count,
        per_regime_n=per_regime_n,
        skipped_regimes=skipped,
    )
