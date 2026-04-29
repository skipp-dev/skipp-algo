"""Sprint C3.1 — Generic BCa + Stationary-Block Bootstrap helpers.

Wraps the per-statistic BCa logic that was previously private to
``scripts/performance_inference._bca_ci`` so any caller (Per-Familie ML
brier intervals, regime-stratified PSR, RL implementation-shortfall) can
use BCa without re-implementing the math. The stationary-block
resampling primitive is implemented in this module alongside the BCa
helpers so callers have a single import surface.

API surface::

    from smc_core.inference.bootstrap import bootstrap_ci

    res = bootstrap_ci(
        sample,
        statistic=lambda x: x.mean(),
        method="bca",       # "percentile" | "basic" | "bca"
        B=1000,
        seed=0,
        block_length=1,     # >1 selects stationary-block resampling
    )
    res["ci_low"], res["ci_high"], res["point"], res["method"]

Pure NumPy. Determinism pinned by ``seed``.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c31
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import erf, sqrt
from typing import Literal, TypedDict

import numpy as np

CIMethod = Literal["percentile", "basic", "bca"]


class BootstrapResult(TypedDict):
    point: float
    ci_low: float
    ci_high: float
    method: CIMethod
    B: int
    n: int
    block_length: int
    alpha: float


# ---------------------------------------------------------------------------
# helpers (mirrors of scripts/performance_inference internals)
# ---------------------------------------------------------------------------


def _normal_quantile(p: float) -> float:
    """Inverse standard-normal CDF (Beasley-Springer / Moro), no scipy."""
    p = float(p)
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = (-2.0 * np.log(p)) ** 0.5
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    q = (-2.0 * np.log(1.0 - p)) ** 0.5
    return -(
        (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    )


def _phi(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _validate(sample: np.ndarray) -> np.ndarray:
    arr = np.asarray(sample, dtype=np.float64).ravel()
    if arr.size == 0:
        raise ValueError("sample must be non-empty")
    if not np.all(np.isfinite(arr)):
        raise ValueError("sample must contain only finite values")
    return arr


# ---------------------------------------------------------------------------
# resamplers
# ---------------------------------------------------------------------------


def _iid_resample(arr: np.ndarray, B: int, rng: np.random.Generator) -> np.ndarray:
    n = arr.size
    idx = rng.integers(0, n, size=(B, n), dtype=np.int64)
    return arr[idx]


def _stationary_resample(
    arr: np.ndarray, B: int, mean_block_length: int, rng: np.random.Generator
) -> np.ndarray:
    """Politis-Romano stationary block bootstrap."""
    n = arr.size
    p = 1.0 / max(mean_block_length, 1)
    out = np.empty((B, n), dtype=arr.dtype)
    for b in range(B):
        starts = rng.integers(0, n, size=n, dtype=np.int64)
        breaks = rng.random(size=n) < p
        idx = np.empty(n, dtype=np.int64)
        cur = int(starts[0])
        for k in range(n):
            if k > 0 and breaks[k]:
                cur = int(starts[k])
            idx[k] = cur % n
            cur += 1
        out[b] = arr[idx]
    return out


# ---------------------------------------------------------------------------
# CI methods
# ---------------------------------------------------------------------------


def _percentile(boot: np.ndarray, alpha: float) -> tuple[float, float]:
    return (
        float(np.quantile(boot, alpha / 2.0)),
        float(np.quantile(boot, 1.0 - alpha / 2.0)),
    )


def _basic(boot: np.ndarray, observed: float, alpha: float) -> tuple[float, float]:
    lo, hi = _percentile(boot, alpha)
    return 2.0 * observed - hi, 2.0 * observed - lo


def _bca(
    boot: np.ndarray,
    observed: float,
    jackknife: np.ndarray,
    alpha: float,
) -> tuple[float, float]:
    proportion_below = float(np.mean(boot < observed))
    proportion_below = min(max(proportion_below, 1e-9), 1.0 - 1e-9)
    z0 = _normal_quantile(proportion_below)
    jk_mean = float(jackknife.mean())
    diff = jk_mean - jackknife
    num = float((diff ** 3).sum())
    den = float(6.0 * (diff ** 2).sum() ** 1.5)
    a = num / den if den > 0 else 0.0
    z_lo = _normal_quantile(alpha / 2.0)
    z_hi = _normal_quantile(1.0 - alpha / 2.0)
    p_lo = _phi(z0 + (z0 + z_lo) / max(1.0 - a * (z0 + z_lo), 1e-9))
    p_hi = _phi(z0 + (z0 + z_hi) / max(1.0 - a * (z0 + z_hi), 1e-9))
    p_lo = min(max(p_lo, 1e-9), 1.0 - 1e-9)
    p_hi = min(max(p_hi, 1e-9), 1.0 - 1e-9)
    return float(np.quantile(boot, p_lo)), float(np.quantile(boot, p_hi))


def _jackknife(arr: np.ndarray, statistic: Callable[[np.ndarray], float]) -> np.ndarray:
    n = arr.size
    out = np.empty(n, dtype=np.float64)
    mask = np.ones(n, dtype=bool)
    for i in range(n):
        mask[i] = False
        out[i] = float(statistic(arr[mask]))
        mask[i] = True
    return out


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BootstrapConfig:
    method: CIMethod = "percentile"
    alpha: float = 0.05
    B: int = 1000
    seed: int = 0
    block_length: int = 1


def bootstrap_ci(
    sample: np.ndarray,
    *,
    statistic: Callable[[np.ndarray], float],
    method: CIMethod = "percentile",
    alpha: float = 0.05,
    B: int = 1000,
    seed: int = 0,
    block_length: int = 1,
) -> BootstrapResult:
    """Compute a bootstrap CI for ``statistic`` over ``sample``.

    Parameters
    ----------
    sample:
        1-D array of observations.
    statistic:
        Callable mapping a 1-D NumPy array to a scalar (mean, std,
        win-rate, Sharpe, profit-factor, …).
    method:
        ``"percentile"`` | ``"basic"`` | ``"bca"``. BCa adds a jackknife
        pass; cost is ``O(n)`` extra statistic evaluations.
    alpha:
        Two-sided CI level (default 0.05 -> 95 % CI).
    B:
        Number of bootstrap resamples.
    seed:
        Determinism pin.
    block_length:
        ``1`` (default) selects classical iid resampling; ``> 1``
        selects Politis-Romano stationary block resampling with the
        given expected block length.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha out of range: {alpha}")
    if B <= 0:
        raise ValueError(f"B must be positive, got {B}")
    if block_length < 1:
        raise ValueError(f"block_length must be >= 1, got {block_length}")
    arr = _validate(sample)
    rng = np.random.default_rng(seed)

    resamples = _iid_resample(arr, B, rng) if block_length == 1 else _stationary_resample(arr, B, block_length, rng)

    boot = np.array([statistic(resamples[i]) for i in range(B)], dtype=np.float64)
    observed = float(statistic(arr))

    if method == "percentile":
        lo, hi = _percentile(boot, alpha)
    elif method == "basic":
        lo, hi = _basic(boot, observed, alpha)
    elif method == "bca":
        if arr.size < 2:
            raise ValueError(
                f"method='bca' requires at least 2 observations, got n={arr.size}"
            )
        jk = _jackknife(arr, statistic)
        lo, hi = _bca(boot, observed, jk, alpha)
    else:  # pragma: no cover - guarded by Literal
        raise ValueError(f"unknown method: {method}")

    return BootstrapResult(
        point=observed,
        ci_low=float(lo),
        ci_high=float(hi),
        method=method,
        B=int(B),
        n=int(arr.size),
        block_length=int(block_length),
        alpha=float(alpha),
    )


__all__ = [
    "BootstrapConfig",
    "BootstrapResult",
    "CIMethod",
    "bootstrap_ci",
]
