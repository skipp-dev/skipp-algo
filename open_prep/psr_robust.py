"""Sprint C6.1 — PSR slippage adjustment + robust-moments wrapper.

The canonical Bailey-Lopez-de-Prado PSR lives in
:mod:`open_prep.stats_helpers.probabilistic_sharpe`. C6.1 adds two
opt-in extensions on top of it (no behavioural change to the existing
function):

1. **Slippage / Min-IS adjustment.** Brutto-Sharpe overstates the edge
   the strategy will actually keep after costs. ``compute_psr_minIS``
   subtracts a per-trade slippage series (in basis points) from each
   return before computing PSR, returning both the brutto and net PSR
   so the operator can see what the cost layer ate.

2. **Robust moments.** Outlier bars (earnings gaps, halts) inflate the
   sample skew/kurtosis terms in PSR's denominator and cause
   month-to-month flicker. ``probabilistic_sharpe_robust`` supports
   ``moments_estimator='winsorized'`` (symmetric trim of the alpha-tails
   before sample skew/kurtosis are computed).

Out of scope:
- Backfill of historical PSR (separate adoption PR).
- Hodges-Lehmann estimator (deferred until a benchmark on real PnL
  shows it's worth the extra moment-passes).

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c61
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from open_prep.stats_helpers import (
    MIN_OBSERVATIONS_FOR_PSR,
    compute_skew_kurtosis,
    probabilistic_sharpe,
)

MomentsEstimator = Literal["sample", "winsorized"]


def compute_psr_minIS(
    returns: Sequence[float],
    *,
    slippage_bps_series: Sequence[float] | None = None,
    sr_star: float = 0.0,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> dict[str, float | bool]:
    """PSR with optional slippage adjustment.

    The slippage series is interpreted as cost in basis points per trade
    (positive ⇒ adverse). It is converted to the same fractional units
    as ``returns`` (``cost = bps / 1e4``) and subtracted bar-by-bar
    before PSR is computed. ``slippage_bps_series=None`` is identical to
    :func:`probabilistic_sharpe` and is kept as a feature-flag.

    Returns the PSR-result dict augmented with:
      - ``psr_brutto``: PSR on the unadjusted return stream.
      - ``mean_slippage_bps``: average per-bar cost (audit).
      - ``slippage_adjusted``: bool flag for downstream consumers.
    """
    if slippage_bps_series is None:
        out = probabilistic_sharpe(
            returns,
            sr_star=sr_star,
            annualize=annualize,
            periods_per_year=periods_per_year,
        )
        out["psr_brutto"] = out["psr"]
        out["mean_slippage_bps"] = 0.0
        out["slippage_adjusted"] = False
        return out

    if len(slippage_bps_series) != len(returns):
        raise ValueError(
            f"slippage_bps_series length {len(slippage_bps_series)} != "
            f"returns length {len(returns)}"
        )

    brutto = probabilistic_sharpe(
        returns,
        sr_star=sr_star,
        annualize=annualize,
        periods_per_year=periods_per_year,
    )

    net_returns = [r - (s / 1e4) for r, s in zip(returns, slippage_bps_series, strict=False)]
    net = probabilistic_sharpe(
        net_returns,
        sr_star=sr_star,
        annualize=annualize,
        periods_per_year=periods_per_year,
    )
    net["psr_brutto"] = brutto["psr"]
    net["mean_slippage_bps"] = sum(slippage_bps_series) / len(slippage_bps_series)
    net["slippage_adjusted"] = True
    return net


def _winsorize(values: Sequence[float], alpha: float) -> list[float]:
    """Symmetric trim: clamp values outside the (alpha, 1-alpha) quantiles."""
    if not (0.0 < alpha < 0.5):
        raise ValueError(f"alpha must be in (0, 0.5), got {alpha}")
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    lo_idx = max(0, math.floor(alpha * n))
    hi_idx = min(n - 1, math.ceil((1.0 - alpha) * n) - 1)
    lo = sorted_vals[lo_idx]
    hi = sorted_vals[hi_idx]
    return [min(max(v, lo), hi) for v in values]


def probabilistic_sharpe_robust(
    returns: Sequence[float],
    *,
    sr_star: float = 0.0,
    moments_estimator: MomentsEstimator = "sample",
    winsor_alpha: float = 0.025,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> dict[str, float]:
    """PSR with a swappable skew/kurtosis estimator.

    ``moments_estimator='sample'`` (default) reproduces
    :func:`probabilistic_sharpe` bit-exact. ``'winsorized'`` symmetrically
    trims the ``winsor_alpha`` tails before computing the sample skew
    and kurtosis used in the PSR denominator — this stabilises the
    estimate when the return stream contains a small number of huge
    outlier bars (earnings gaps, halts, fat-finger prints).

    Note: only the **moment terms** are winsorized. The Sharpe estimate
    itself is unchanged so the point statistic remains identifiable.

    Returns the same keys as :func:`probabilistic_sharpe` plus
    ``moments_estimator`` (numeric flag: ``0.0`` for ``"sample"``,
    ``1.0`` for ``"winsorized"`` — the dict is ``dict[str, float]``).
    """
    n = len(returns)
    if n < MIN_OBSERVATIONS_FOR_PSR:
        raise ValueError(
            f"need at least {MIN_OBSERVATIONS_FOR_PSR} observations, got {n}"
        )

    if moments_estimator == "sample":
        out = probabilistic_sharpe(
            returns,
            sr_star=sr_star,
            annualize=annualize,
            periods_per_year=periods_per_year,
        )
        out["moments_estimator"] = 0.0
        return out

    if moments_estimator != "winsorized":
        raise ValueError(
            f"moments_estimator must be 'sample' or 'winsorized', got {moments_estimator!r}"
        )

    trimmed = _winsorize(returns, winsor_alpha)
    skew_w, kurt_w = compute_skew_kurtosis(trimmed)
    # Compute Sharpe on the *original* returns (point statistic preserved),
    # then plug the robust moments into the closed-form PSR formula.
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var <= 0.0:
        raise ValueError("variance is zero — returns are constant")
    sharpe = mean / math.sqrt(var)
    # Match probabilistic_sharpe's convention: the internal Sharpe stays
    # at per-period frequency. Only sr_star (caller-supplied, possibly
    # annual) is rescaled back to per-period for comparison.
    sr_internal = sharpe
    sr_star_internal = sr_star / math.sqrt(periods_per_year) if annualize else sr_star

    denom_inner = 1.0 - skew_w * sr_internal + ((kurt_w - 1.0) / 4.0) * sr_internal ** 2
    if denom_inner <= 0.0:
        return {
            "psr": 0.5,
            "sharpe_hat": sr_internal,
            "sr_star": sr_star_internal,
            "skew": skew_w,
            "kurtosis": kurt_w,
            "n": float(n),
            "degenerate": 1.0,
            "moments_estimator": 1.0,
        }

    z = (sr_internal - sr_star_internal) * math.sqrt(n - 1) / math.sqrt(denom_inner)
    return {
        "psr": 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))),
        "sharpe_hat": sr_internal,
        "sr_star": sr_star_internal,
        "skew": skew_w,
        "kurtosis": kurt_w,
        "n": float(n),
        "moments_estimator": 1.0,
    }


__all__ = [
    "MomentsEstimator",
    "compute_psr_minIS",
    "probabilistic_sharpe_robust",
]
