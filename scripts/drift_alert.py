"""Drift detection for live trade outcomes vs backtest baseline (Sprint C9 / T2-T4).

Core helpers for the Drift-Alert sprint:

- ``ks_two_sample`` — exact Kolmogorov-Smirnov two-sample statistic + an
  asymptotic p-value, no scipy dependency
- ``population_stability_index`` — PSI score with the standard
  ``[<0.10, 0.10-0.25, >0.25]`` traffic-light bands
- ``rolling_drift_score`` — sliding-window comparison of a live metric
  series against a fixed baseline mean ± std (z-style)
- ``compute_drift_report`` — top-level dict the watchdog cron emits to
  ``artifacts/drift/``

Pure stdlib + numpy. Independent of every other C-module so it can ship
ahead of the rest of the C9 sprint.

References
----------
- Kolmogorov-Smirnov asymptotic p-value:
  https://en.wikipedia.org/wiki/Kolmogorov%E2%80%93Smirnov_test
- PSI bands per Siddiqi, *Credit Risk Scorecards* (2006).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np

DriftSeverity = Literal["green", "yellow", "red"]


@dataclass(frozen=True)
class DriftFinding:
    """Single per-metric drift observation."""

    metric: str
    statistic: float
    p_value: float | None
    severity: DriftSeverity
    n_baseline: int
    n_live: int


# ---------------------------------------------------------------------------
# Kolmogorov-Smirnov two-sample
# ---------------------------------------------------------------------------


def ks_two_sample(
    baseline: Sequence[float] | np.ndarray,
    live: Sequence[float] | np.ndarray,
) -> tuple[float, float | None]:
    """Two-sample KS statistic and asymptotic p-value.

    Returns ``(statistic, p_value)``. ``p_value`` is ``None`` when
    either sample is empty. The p-value uses the asymptotic
    Kolmogorov-Smirnov distribution and is exact in the limit of
    large samples; for small n it is conservative.
    """

    a = np.sort(np.asarray(baseline, dtype=np.float64))
    b = np.sort(np.asarray(live, dtype=np.float64))
    n_a = len(a)
    n_b = len(b)
    if n_a == 0 or n_b == 0:
        return 0.0, None

    # Merge unique values; CDFs evaluated at each unique sample.
    data_all = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, data_all, side="right") / n_a
    cdf_b = np.searchsorted(b, data_all, side="right") / n_b
    statistic = float(np.max(np.abs(cdf_a - cdf_b)))

    # Asymptotic p-value via the Kolmogorov distribution series:
    #   Q(λ) = 2 Σ_{k=1..∞} (-1)^{k-1} exp(-2 k² λ²)
    en = math.sqrt(n_a * n_b / (n_a + n_b))
    lam = (en + 0.12 + 0.11 / en) * statistic
    p = _kolmogorov_q(lam)
    return statistic, p


def _kolmogorov_q(lam: float) -> float:
    """Tail of the Kolmogorov distribution Q(λ); clamped to [0, 1]."""

    if lam <= 0:
        return 1.0
    total = 0.0
    sign = 1.0
    for k in range(1, 101):
        term = sign * math.exp(-2.0 * (k * lam) ** 2)
        total += term
        if abs(term) < 1e-12:
            break
        sign = -sign
    p = 2.0 * total
    return max(0.0, min(1.0, p))


# ---------------------------------------------------------------------------
# Population stability index
# ---------------------------------------------------------------------------


def population_stability_index(
    baseline: Sequence[float] | np.ndarray,
    live: Sequence[float] | np.ndarray,
    *,
    n_buckets: int = 10,
) -> float | None:
    """Population stability index between two samples.

    Buckets are quantiles of the *baseline* distribution. Returns
    ``None`` when either sample is empty or the baseline is degenerate
    (all-equal values). A small epsilon protects against zero-bucket
    log blow-ups.
    """

    a = np.asarray(baseline, dtype=np.float64)
    b = np.asarray(live, dtype=np.float64)
    if a.size == 0 or b.size == 0:
        return None
    if n_buckets < 2:
        raise ValueError("n_buckets must be >= 2")

    qs = np.linspace(0.0, 1.0, n_buckets + 1)
    edges = np.quantile(a, qs)
    # Degenerate baseline → no spread to bucket against.
    if edges[0] == edges[-1]:
        return None
    edges[0] = -np.inf
    edges[-1] = np.inf

    a_counts, _ = np.histogram(a, bins=edges)
    b_counts, _ = np.histogram(b, bins=edges)
    eps = 1e-6
    a_pct = (a_counts / a.size) + eps
    b_pct = (b_counts / b.size) + eps
    psi = float(np.sum((b_pct - a_pct) * np.log(b_pct / a_pct)))
    return psi


def psi_severity(psi: float) -> DriftSeverity:
    """Standard PSI traffic-light bands (Siddiqi 2006)."""

    if psi < 0.10:
        return "green"
    if psi < 0.25:
        return "yellow"
    return "red"


# ---------------------------------------------------------------------------
# Rolling-window z-style drift score
# ---------------------------------------------------------------------------


def rolling_drift_score(
    live_series: Sequence[float] | np.ndarray,
    *,
    baseline_mean: float,
    baseline_std: float,
    window: int = 20,
) -> list[float]:
    """Per-window |z|-score of live data against a baseline (mean, std).

    Returns one score per sliding window. Windows shorter than
    ``window`` at the start of the series are skipped. ``baseline_std``
    must be strictly positive; degenerate baselines should be caught
    upstream.
    """

    if baseline_std <= 0:
        raise ValueError("baseline_std must be strictly positive")
    if window < 1:
        raise ValueError("window must be >= 1")

    arr = np.asarray(live_series, dtype=np.float64)
    if arr.size < window:
        return []
    out: list[float] = []
    for i in range(window, arr.size + 1):
        chunk = arr[i - window : i]
        z = abs((float(chunk.mean()) - baseline_mean) / baseline_std)
        out.append(z)
    return out


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------


def compute_drift_report(
    metrics: dict[str, tuple[Sequence[float] | np.ndarray, Sequence[float] | np.ndarray]],
    *,
    p_value_yellow: float = 0.05,
    p_value_red: float = 0.01,
) -> dict[str, object]:
    """Build a per-metric drift report consumed by the watchdog cron.

    ``metrics`` maps metric-name → ``(baseline_samples, live_samples)``.
    Each metric gets a KS statistic + p-value; severity is mapped from
    the p-value. The aggregate severity is the worst per-metric
    severity.
    """

    findings: list[DriftFinding] = []
    for name, (baseline, live) in metrics.items():
        stat, p = ks_two_sample(baseline, live)
        if p is None:
            severity: DriftSeverity = "green"
        elif p < p_value_red:
            severity = "red"
        elif p < p_value_yellow:
            severity = "yellow"
        else:
            severity = "green"
        findings.append(
            DriftFinding(
                metric=name,
                statistic=stat,
                p_value=p,
                severity=severity,
                n_baseline=len(baseline),
                n_live=len(live),
            )
        )

    aggregate = "green"
    for f in findings:
        if f.severity == "red":
            aggregate = "red"
            break
        if f.severity == "yellow":
            aggregate = "yellow"

    return {
        "aggregate_severity": aggregate,
        "n_metrics": len(findings),
        "findings": [
            {
                "metric": f.metric,
                "statistic": round(f.statistic, 6),
                "p_value": (None if f.p_value is None else round(f.p_value, 6)),
                "severity": f.severity,
                "n_baseline": f.n_baseline,
                "n_live": f.n_live,
            }
            for f in findings
        ],
    }
