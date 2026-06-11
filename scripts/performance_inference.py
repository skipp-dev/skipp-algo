"""Performance inference: bootstrap CIs for Sharpe, MaxDD, win-rate, profit-factor.

Sprint C3 / T3 — see ``docs/SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md``.

This module sits one layer above ``scripts/bootstrap_methods.py``: it
takes a 1-D return series (or trade outcomes) and emits a confidence
interval for the metric of interest. The CI methods are deliberately
selected per metric — see ``docs/SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md``
T1 for the rationale:

    Sharpe         -> studentized + stationary block (Ledoit-Wolf 2008)
    MaxDD          -> percentile + stationary block (path-dependent)
    Win-rate       -> BCa + IID (Bernoulli, no auto-correlation)
    Profit-factor  -> BCa + IID

All helpers return a flat dict that maps 1:1 to the JSON schema fields
in ``docs/calibration/calibration_report_public.json`` (T6).
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from scripts.bootstrap_methods import (
    DEFAULT_B,
    DEFAULT_MEAN_BLOCK_LENGTH,
    DEFAULT_SEED,
    MIN_EVENTS_FOR_BOOTSTRAP,
    iid_bootstrap,
    make_resamples,
    stationary_block_bootstrap,
)

CIMethod = Literal["studentized", "bca", "percentile"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _skipped(reason: str, **extra: object) -> dict[str, object]:
    return {"skipped_reason": reason, **extra}


def _normal_quantile(p: float) -> float:
    """Inverse standard-normal CDF (Beasley-Springer-Moro is overkill here).

    Uses scipy if available, falls back to the same numpy-only Beasley-
    Springer approximation that ``scripts/run_ab_comparison.py`` uses.
    """

    try:
        from scipy.stats import norm  # type: ignore[import-not-found]

        return float(norm.ppf(p))
    except ImportError:  # pragma: no cover - scipy is in requirements.txt
        # Acklam's rational approximation (max abs err ~1.15e-9).
        # Implementation kept short on purpose; full reference:
        # https://web.archive.org/web/20150910044729/http://home.online.no/~pjacklam/notes/invnorm/
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
            q = float(np.sqrt(-2.0 * np.log(p)))
            return (
                (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
                / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
            )
        if p <= phigh:
            q = p - 0.5
            r = q * q
            return (
                (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
                * q
                / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
            )
        q = float(np.sqrt(-2.0 * np.log(1.0 - p)))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )


def _percentile_ci(boot: np.ndarray, alpha: float) -> tuple[float, float]:
    lo = float(np.quantile(boot, alpha / 2.0))
    hi = float(np.quantile(boot, 1.0 - alpha / 2.0))
    return lo, hi


def _bca_ci(
    boot: np.ndarray, observed: float, jackknife: np.ndarray, alpha: float
) -> tuple[float, float]:
    """Bias-corrected and accelerated CI (Efron, 1987)."""

    # Bias-correction z0.
    proportion_below = float(np.mean(boot < observed))
    # Clamp to (0, 1) to keep the inverse normal finite.
    proportion_below = min(max(proportion_below, 1e-9), 1.0 - 1e-9)
    z0 = _normal_quantile(proportion_below)
    # Acceleration via jackknife.
    jk_mean = float(jackknife.mean())
    diff = jk_mean - jackknife
    num = float((diff**3).sum())
    den = float(6.0 * (diff**2).sum() ** 1.5)
    a = num / den if den > 0 else 0.0
    # Adjusted percentiles.
    z_alpha_lo = _normal_quantile(alpha / 2.0)
    z_alpha_hi = _normal_quantile(1.0 - alpha / 2.0)
    p_lo_num = z0 + z_alpha_lo
    p_hi_num = z0 + z_alpha_hi
    p_lo = _phi(z0 + p_lo_num / (1.0 - a * p_lo_num))
    p_hi = _phi(z0 + p_hi_num / (1.0 - a * p_hi_num))
    # C-sprint deep-review C3: ``_phi`` returns a value in (0, 1) so
    # numerically ``p_lo``/``p_hi`` may land within 1e-12 of the
    # boundary and trigger an opaque ``np.quantile`` warning. Clamp
    # to a safe interior just like ``proportion_below`` above so the
    # quantile lookup is always well-defined.
    p_lo = min(max(p_lo, 1e-9), 1.0 - 1e-9)
    p_hi = min(max(p_hi, 1e-9), 1.0 - 1e-9)
    lo = float(np.quantile(boot, p_lo))
    hi = float(np.quantile(boot, p_hi))
    return lo, hi


def _phi(x: float) -> float:
    """Standard-normal CDF via erfc (avoids scipy dependency in hot path)."""

    from math import erf, sqrt

    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------


def _sharpe_periodic(returns: np.ndarray) -> float:
    sd = float(returns.std(ddof=1))
    if sd == 0.0:
        return float("nan")
    return float(returns.mean()) / sd


def sharpe_ci(
    returns: np.ndarray,
    *,
    alpha: float = 0.05,
    freq: float = 252,
    B: int = DEFAULT_B,
    mean_block_length: int = DEFAULT_MEAN_BLOCK_LENGTH,
    method: CIMethod = "studentized",
    seed: int = DEFAULT_SEED,
    min_events: int = MIN_EVENTS_FOR_BOOTSTRAP,
) -> dict[str, object]:
    """Bootstrap CI for the annualized Sharpe ratio.

    ``method="studentized"`` (default) follows Ledoit & Wolf (2008): we
    pivot on the studentized statistic
    :math:`(SR^* - SR) / \\hat{SE}(SR^*)` and invert quantiles.
    """

    arr = np.asarray(returns, dtype=np.float64).ravel()
    if arr.size < min_events:
        return _skipped("insufficient_trades", n=int(arr.size), min_events=int(min_events))

    sqrt_freq = float(np.sqrt(freq))
    sr_obs_periodic = _sharpe_periodic(arr)
    sr_obs = sr_obs_periodic * sqrt_freq

    if method == "studentized":
        boot = stationary_block_bootstrap(
            arr, mean_block_length=mean_block_length, B=B, seed=seed
        )
        # Vectorized periodic Sharpe per row.
        mu = boot.mean(axis=1)
        sd = boot.std(axis=1, ddof=1)
        sd_safe = np.where(sd == 0.0, np.nan, sd)
        sr_boot_periodic = mu / sd_safe
        # Studentized pivot uses the bootstrap distribution of
        # (SR* - SR_hat) / SE(SR*). For periodic Sharpe with
        # iid-ish returns, SE(SR*) ≈ sqrt((1 + 0.5 SR*^2) / n).
        # See Lo (2002) — also reproduced by Ledoit-Wolf for the
        # studentized variant.
        n = arr.size
        se_boot = np.sqrt((1.0 + 0.5 * sr_boot_periodic**2) / n)
        se_obs = float(np.sqrt((1.0 + 0.5 * sr_obs_periodic**2) / n))
        # Drop NaN rows (zero-variance resamples).
        mask = np.isfinite(sr_boot_periodic) & np.isfinite(se_boot) & (se_boot > 0)
        pivot = (sr_boot_periodic[mask] - sr_obs_periodic) / se_boot[mask]
        q_lo = float(np.quantile(pivot, 1.0 - alpha / 2.0))
        q_hi = float(np.quantile(pivot, alpha / 2.0))
        ci_low_periodic = sr_obs_periodic - q_lo * se_obs
        ci_high_periodic = sr_obs_periodic - q_hi * se_obs
        ci_low = float(ci_low_periodic) * sqrt_freq
        ci_high = float(ci_high_periodic) * sqrt_freq
    elif method == "percentile":
        boot = stationary_block_bootstrap(
            arr, mean_block_length=mean_block_length, B=B, seed=seed
        )
        sr_boot = (boot.mean(axis=1) / np.where(boot.std(axis=1, ddof=1) == 0, np.nan, boot.std(axis=1, ddof=1))) * sqrt_freq
        sr_boot = sr_boot[np.isfinite(sr_boot)]
        ci_low, ci_high = _percentile_ci(sr_boot, alpha)
    elif method == "bca":
        boot = stationary_block_bootstrap(
            arr, mean_block_length=mean_block_length, B=B, seed=seed
        )
        sr_boot = (boot.mean(axis=1) / np.where(boot.std(axis=1, ddof=1) == 0, np.nan, boot.std(axis=1, ddof=1))) * sqrt_freq
        sr_boot = sr_boot[np.isfinite(sr_boot)]
        # Vectorised leave-one-out Sharpe (was O(n^2) via np.delete in
        # a Python loop). Use the closed-form leave-one-out mean/var so
        # the jackknife is O(n) — material for n in the few-hundreds
        # range we hit on per-variant tracks.
        n = arr.size
        if n >= 2:
            total = float(arr.sum())
            sq_total = float((arr * arr).sum())
            loo_mean = (total - arr) / (n - 1)
            # Population sum of squared deviations for the leave-one-out
            # subset, then convert to sample variance with ddof=1.
            loo_sumsq = sq_total - arr * arr - (n - 1) * (loo_mean * loo_mean)
            loo_var = loo_sumsq / (n - 2) if n >= 3 else np.zeros_like(loo_mean)
            loo_std = np.sqrt(np.where(loo_var > 0, loo_var, np.nan))
            jk = np.where(loo_std > 0, loo_mean / loo_std, np.nan) * sqrt_freq
            jk = jk[np.isfinite(jk)]
        else:
            jk = np.empty(0, dtype=np.float64)
        if jk.size < 2:
            # Fall back to percentile CI when the jackknife collapses.
            ci_low, ci_high = _percentile_ci(sr_boot, alpha)
        else:
            ci_low, ci_high = _bca_ci(sr_boot, sr_obs, jk, alpha)
    else:
        raise ValueError(f"unknown method: {method!r}")

    return {
        "metric": "sharpe",
        "value": float(sr_obs),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "ci_method": method,
        "alpha": float(alpha),
        "B": int(B),
        "block_length": int(mean_block_length),
        "freq": int(freq),
        "n": int(arr.size),
    }


# ---------------------------------------------------------------------------
# MaxDD
# ---------------------------------------------------------------------------


def _max_drawdown_from_returns(returns: np.ndarray) -> float:
    """Max drawdown of the equity curve built from per-period returns.

    Returns a non-negative magnitude (e.g. 0.15 == 15% drawdown).
    """

    equity = np.cumprod(1.0 + returns)
    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    return float(-drawdown.min())


def max_dd_ci(
    returns: np.ndarray,
    *,
    alpha: float = 0.05,
    B: int = DEFAULT_B,
    mean_block_length: int = DEFAULT_MEAN_BLOCK_LENGTH,
    seed: int = DEFAULT_SEED,
    min_events: int = MIN_EVENTS_FOR_BOOTSTRAP,
) -> dict[str, object]:
    """Percentile bootstrap CI for max drawdown.

    MaxDD is path-dependent, so the bootstrap resamples *trade returns*
    in blocks (preserving any clustering of losses) and rebuilds the
    equity curve per resample.
    """

    arr = np.asarray(returns, dtype=np.float64).ravel()
    if arr.size < min_events:
        return _skipped("insufficient_trades", n=int(arr.size), min_events=int(min_events))

    boot = stationary_block_bootstrap(
        arr, mean_block_length=mean_block_length, B=B, seed=seed
    )
    # Vectorized equity curve and drawdown per row.
    equity = np.cumprod(1.0 + boot, axis=1)
    running_max = np.maximum.accumulate(equity, axis=1)
    dd = (equity - running_max) / running_max
    dd_max = -dd.min(axis=1)
    ci_low, ci_high = _percentile_ci(dd_max, alpha)
    return {
        "metric": "max_dd",
        "value": float(_max_drawdown_from_returns(arr)),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "ci_method": "percentile",
        "alpha": float(alpha),
        "B": int(B),
        "block_length": int(mean_block_length),
        "n": int(arr.size),
    }


# ---------------------------------------------------------------------------
# Win-rate (Bernoulli) — IID + BCa
# ---------------------------------------------------------------------------


def win_rate_ci(
    outcomes: np.ndarray,
    *,
    alpha: float = 0.05,
    B: int = DEFAULT_B,
    method: CIMethod = "bca",
    seed: int = DEFAULT_SEED,
    min_events: int = MIN_EVENTS_FOR_BOOTSTRAP,
) -> dict[str, object]:
    """CI for win-rate. ``outcomes`` are 0/1 ints (or bools)."""

    arr = np.asarray(outcomes, dtype=np.float64).ravel()
    if arr.size < min_events:
        return _skipped("insufficient_trades", n=int(arr.size), min_events=int(min_events))
    if not np.all((arr == 0.0) | (arr == 1.0)):
        raise ValueError("outcomes must contain only 0 or 1 values")

    observed = float(arr.mean())
    boot = iid_bootstrap(arr, B=B, seed=seed)
    boot_rates = boot.mean(axis=1)

    if method == "percentile":
        ci_low, ci_high = _percentile_ci(boot_rates, alpha)
    elif method == "bca":
        # Jackknife of win-rate.
        n = arr.size
        total = float(arr.sum())
        # Leave-one-out mean: (total - x_i) / (n - 1).
        jk = (total - arr) / float(n - 1)
        ci_low, ci_high = _bca_ci(boot_rates, observed, jk, alpha)
    else:
        raise ValueError(f"unknown method for win_rate_ci: {method!r}")

    return {
        "metric": "win_rate",
        "value": observed,
        "ci_low": float(max(ci_low, 0.0)),
        "ci_high": float(min(ci_high, 1.0)),
        "ci_method": method,
        "alpha": float(alpha),
        "B": int(B),
        "n": int(arr.size),
    }


# ---------------------------------------------------------------------------
# Profit-factor — IID + BCa
# ---------------------------------------------------------------------------


def _profit_factor(pnl: np.ndarray) -> float:
    pos = float(pnl[pnl > 0].sum())
    neg = -float(pnl[pnl < 0].sum())
    if neg == 0.0:
        return float("inf") if pos > 0 else float("nan")
    return pos / neg


def profit_factor_ci(
    pnl: np.ndarray,
    *,
    alpha: float = 0.05,
    B: int = DEFAULT_B,
    method: CIMethod = "percentile",
    seed: int = DEFAULT_SEED,
    min_events: int = MIN_EVENTS_FOR_BOOTSTRAP,
) -> dict[str, object]:
    """CI for profit-factor (= sum positive PnL / |sum negative PnL|)."""

    arr = np.asarray(pnl, dtype=np.float64).ravel()
    if arr.size < min_events:
        return _skipped("insufficient_trades", n=int(arr.size), min_events=int(min_events))

    observed = _profit_factor(arr)
    boot = iid_bootstrap(arr, B=B, seed=seed)
    pos = np.where(boot > 0, boot, 0.0).sum(axis=1)
    neg = -np.where(boot < 0, boot, 0.0).sum(axis=1)
    pf_boot = np.where(neg > 0, pos / np.where(neg == 0, np.nan, neg), np.inf)
    pf_finite = pf_boot[np.isfinite(pf_boot)]

    if pf_finite.size < 10:
        return _skipped("degenerate_resamples_no_losses", n=int(arr.size), B=int(B))

    if method == "percentile":
        ci_low, ci_high = _percentile_ci(pf_finite, alpha)
    elif method == "bca":
        n = arr.size
        # Vectorized leave-one-out profit factor.
        total_pos = float(arr[arr > 0].sum())
        total_neg = -float(arr[arr < 0].sum())
        loo_pos = total_pos - np.where(arr > 0, arr, 0.0)
        loo_neg = total_neg - np.where(arr < 0, -arr, 0.0)
        jk = np.where(loo_neg > 0, loo_pos / np.where(loo_neg == 0, np.nan, loo_neg), np.nan)
        jk = jk[np.isfinite(jk)]
        if jk.size < n // 2:
            ci_low, ci_high = _percentile_ci(pf_finite, alpha)
        else:
            ci_low, ci_high = _bca_ci(pf_finite, observed, jk, alpha)
    else:
        raise ValueError(f"unknown method for profit_factor_ci: {method!r}")

    return {
        "metric": "profit_factor",
        "value": float(observed),
        "ci_low": float(max(ci_low, 0.0)),
        "ci_high": float(ci_high),
        "ci_method": method,
        "alpha": float(alpha),
        "B": int(B),
        "n": int(arr.size),
    }


__all__ = [
    "make_resamples",
    "max_dd_ci",
    "profit_factor_ci",
    "sharpe_ci",
    "win_rate_ci",
]
