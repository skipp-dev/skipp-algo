"""Statistical helpers for performance evaluation (Sprint C6 / T2-T4).

Implements:

- ``compute_skew_kurtosis`` — biased plug-in skewness + kurtosis (NOT excess),
  consistent with the Bailey-Lopez de Prado (2012) PSR formula.
- ``probabilistic_sharpe`` — PSR(SR*) per Bailey-Lopez de Prado (2012).
- ``min_trl`` — Minimum Track Record Length per Bailey-Lopez de Prado (2012).

Pure stdlib (math.erf-based normal CDF) — no scipy hard-dependency.

Sources:
- Bailey & Lopez de Prado (2012), "The Sharpe Ratio Efficient Frontier"
  http://boston.qwafafew.org/wp-content/uploads/sites/4/2017/01/Lopez_de_Prado_Sharpe.pdf
- Wikipedia, "Deflated Sharpe ratio"
"""

from __future__ import annotations

import math
from typing import Sequence

__all__ = [
    "MIN_OBSERVATIONS_FOR_PSR",
    "compute_sharpe",
    "compute_skew_kurtosis",
    "min_trl",
    "probabilistic_sharpe",
]


# Plug-in skew / kurtosis estimators are unstable for very small n; below
# this threshold we surface ``ValueError`` so callers handle the edge
# rather than getting silently degenerate PSR values.
MIN_OBSERVATIONS_FOR_PSR = 30


def _normal_cdf(x: float) -> float:
    """Standard-normal CDF via math.erf — duplicated from
    ``scripts.run_ab_comparison._normal_cdf`` to keep this module
    importable without pulling the scripts package."""

    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_ppf_one_sided(alpha: float) -> float:
    """Inverse normal CDF for ``1 - alpha`` (upper-tail quantile).

    Acklam's rational approximation (max abs error ~1.15e-9 across
    [1e-12, 1-1e-12]) — pure stdlib, used so we never need scipy at
    runtime for the MinTRL Z-score lookup.
    """

    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0,1), got {alpha}")
    p = 1.0 - alpha
    # Acklam coefficients
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            ((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]
        ) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


def compute_skew_kurtosis(returns: Sequence[float]) -> tuple[float, float]:
    """Biased plug-in skewness and kurtosis (NOT excess kurtosis).

    Uses the population moments (no n/(n-1) correction) to stay
    consistent with Bailey-Lopez de Prado's PSR derivation, which
    treats γ₃, γ₄ as plug-in moments of the empirical distribution.

    Args:
        returns: 1-D sequence of returns. Must have length ≥
            ``MIN_OBSERVATIONS_FOR_PSR``.

    Returns:
        ``(skew, kurtosis)`` — kurtosis is the raw fourth standardised
        moment (Gaussian → 3.0), not excess kurtosis.

    Raises:
        ValueError: if ``len(returns) < MIN_OBSERVATIONS_FOR_PSR`` or
            standard deviation is zero.
    """

    n = len(returns)
    if n < MIN_OBSERVATIONS_FOR_PSR:
        raise ValueError(
            f"need at least {MIN_OBSERVATIONS_FOR_PSR} observations, got {n}"
        )
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    if m2 <= 0.0:
        raise ValueError("variance is zero — returns are constant")
    m3 = sum((r - mean) ** 3 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    sigma = math.sqrt(m2)
    skew = m3 / (sigma ** 3)
    kurtosis = m4 / (m2 ** 2)
    return (skew, kurtosis)


def compute_sharpe(
    returns: Sequence[float],
    *,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> float:
    """Plain Sharpe ratio (mean / std with ddof=1).

    Standalone helper so C6 can be tested without depending on the
    forthcoming C2 ``compute_sharpe`` — when C2 lands, this can be
    deleted in favour of the canonical implementation.
    """

    n = len(returns)
    if n < 2:
        raise ValueError(f"need at least 2 observations, got {n}")
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var <= 0.0:
        raise ValueError("variance is zero — returns are constant")
    sharpe = mean / math.sqrt(var)
    if annualize:
        sharpe *= math.sqrt(periods_per_year)
    return sharpe


def probabilistic_sharpe(
    returns: Sequence[float],
    sr_star: float = 0.0,
    sharpe_hat: float | None = None,
    *,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> dict[str, float]:
    """PSR(SR*) per Bailey-Lopez de Prado (2012).

    PSR(SR*) = Φ( (SR_hat - SR*) · sqrt(n - 1)
                  / sqrt(1 - γ₃·SR_hat + (γ₄ - 1)/4 · SR_hat²) )

    The denominator is the asymptotic variance of the Sharpe estimator
    under non-Gaussian returns (Mertens 2002 / Lo 2002).

    Args:
        returns: 1-D sequence of returns at the chosen frequency.
        sr_star: comparison threshold Sharpe (same frequency as
            ``sharpe_hat``).
        sharpe_hat: pre-computed Sharpe to skip recomputation. If
            ``None``, computed from ``returns`` at the same frequency
            (i.e. ``annualize=False`` for the *internal* SR_hat used
            in the formula).
        annualize: if True, both ``sharpe_hat`` (when computed
            internally) and ``sr_star`` are interpreted as annualised
            and converted back to per-period for the formula.
        periods_per_year: only used when ``annualize=True``.

    Returns:
        Dict with ``psr``, ``sharpe_hat``, ``sr_star``, ``skew``,
        ``kurtosis``, ``n``.
    """

    n = len(returns)
    if n < MIN_OBSERVATIONS_FOR_PSR:
        raise ValueError(
            f"need at least {MIN_OBSERVATIONS_FOR_PSR} observations, got {n}"
        )
    skew, kurtosis = compute_skew_kurtosis(returns)
    if sharpe_hat is None:
        sr_internal = compute_sharpe(returns, annualize=False)
        sr_star_internal = sr_star
        if annualize:
            sr_star_internal = sr_star / math.sqrt(periods_per_year)
    else:
        if annualize:
            sr_internal = sharpe_hat / math.sqrt(periods_per_year)
            sr_star_internal = sr_star / math.sqrt(periods_per_year)
        else:
            sr_internal = sharpe_hat
            sr_star_internal = sr_star

    denom_inner = 1.0 - skew * sr_internal + ((kurtosis - 1.0) / 4.0) * sr_internal ** 2
    if denom_inner <= 0.0:
        # Pathological — non-Gaussian variance term collapsed; fall
        # back to a wide PSR rather than NaN.
        return {
            "psr": 0.5,
            "sharpe_hat": sr_internal,
            "sr_star": sr_star_internal,
            "skew": skew,
            "kurtosis": kurtosis,
            "n": float(n),
            "degenerate": 1.0,
        }
    z = (sr_internal - sr_star_internal) * math.sqrt(n - 1) / math.sqrt(denom_inner)
    return {
        "psr": _normal_cdf(z),
        "sharpe_hat": sr_internal,
        "sr_star": sr_star_internal,
        "skew": skew,
        "kurtosis": kurtosis,
        "n": float(n),
    }


def min_trl(
    sr_hat: float,
    sr_star: float = 0.0,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    alpha: float = 0.05,
) -> int:
    """Minimum Track Record Length per Bailey-Lopez de Prado (2012).

    MinTRL = 1 + (1 - γ₃·SR_hat + (γ₄ - 1)/4 · SR_hat²) · (Z_α / (SR_hat - SR*))²

    All Sharpe values must be at the same frequency (typically per-period,
    not annualised — annualised SR can be passed but Z_α stays unchanged).

    Args:
        sr_hat: observed Sharpe.
        sr_star: comparison threshold Sharpe.
        skew: γ₃, plug-in skewness of the returns.
        kurtosis: γ₄, plug-in kurtosis (NOT excess; Gaussian = 3.0).
        alpha: one-sided significance level (default 0.05 → Z ≈ 1.6449).

    Returns:
        Minimum number of observations (ceil-rounded int) needed to
        distinguish ``sr_hat`` from ``sr_star`` at confidence ``1 - alpha``.

    Raises:
        ValueError: if ``sr_hat <= sr_star`` (no detectable improvement).
    """

    if sr_hat <= sr_star:
        raise ValueError(
            f"sr_hat ({sr_hat}) must be strictly greater than sr_star ({sr_star})"
        )
    z_alpha = _normal_ppf_one_sided(alpha)
    denom_inner = 1.0 - skew * sr_hat + ((kurtosis - 1.0) / 4.0) * sr_hat ** 2
    if denom_inner <= 0.0:
        raise ValueError(
            "non-Gaussian variance term collapsed; check skew/kurtosis inputs"
        )
    n_needed = 1.0 + denom_inner * (z_alpha / (sr_hat - sr_star)) ** 2
    return int(math.ceil(n_needed))
