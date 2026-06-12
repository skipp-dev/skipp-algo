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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from scripts._kolmogorov import kolmogorov_sf_two_sample

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

    # Shared two-sample K-S survival function (scripts/_kolmogorov.py)
    # so drift_alert.py and compute_live_drift.py emit identical p-values.
    n_eff = (n_a * n_b) / (n_a + n_b)
    p = kolmogorov_sf_two_sample(statistic, n_eff)
    return statistic, p


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
    # Deep-Review 2026-04-27 (MINOR): renormalise after the epsilon
    # smoothing so probabilities sum to exactly 1.0. The previous
    # ``(counts / n) + eps`` form left ``a_pct`` summing to
    # ``1 + n_buckets * eps`` and biased PSI slightly upward
    # (toward red). The renormaliser is the standard Laplace-smoothed
    # PMF: ``(c / n + eps) / (1 + n_buckets * eps)`` — algebraically
    # ``(c + eps * n) / (n + eps * n * n_buckets)``.
    norm = 1.0 + n_buckets * eps
    a_pct = (a_counts / a.size + eps) / norm
    b_pct = (b_counts / b.size + eps) / norm
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


# Detector-3 / Detector-4 thresholds.
#
# Mean-shift fires when |mean_live - mean_baseline| / std_baseline >= 0.3.
# Heuristic: 0.3σ is the lower bound of the "small effect" band per Cohen
# (1988); below this the K-S test on equally-sized live samples already
# has < 50% power and the consensus would not lift it. 0.3σ keeps the
# detector independent of K-S without inflating the false-positive
# rate on stationary noise.
#
# Variance-ratio fires outside [0.5, 2.0] — i.e. live volatility doubles
# or halves vs baseline. The factor 2 mirrors the "regime-shift" gate
# used in production-trading post-mortems (e.g. the 2018 vol-regime
# break) and is the same band used by the c9_threshold_replay.py grid
# tool so the two C9 producers stay coupled.
MEAN_SHIFT_FIRE_SIGMA = 0.3
VAR_RATIO_LOW = 0.5
VAR_RATIO_HIGH = 2.0


def _detector_severities(
    baseline: np.ndarray,
    live: np.ndarray,
    *,
    p_value_yellow: float,
    p_value_red: float,
    psi_n_buckets: int,
) -> dict[str, DriftSeverity | None]:
    """Per-metric severity for the four C9 detectors.

    Returns ``{ks, psi, mean_shift, var_ratio}`` with ``None`` for
    detectors that cannot be evaluated (degenerate baseline, empty live,
    etc.) so the caller can distinguish "not fired" from "not evaluable".
    """
    sev: dict[str, DriftSeverity | None] = {
        "ks": None,
        "psi": None,
        "mean_shift": None,
        "var_ratio": None,
    }

    # Detector 1 — K-S
    _stat, p = ks_two_sample(baseline, live)
    if p is not None:
        if p < p_value_red:
            sev["ks"] = "red"
        elif p < p_value_yellow:
            sev["ks"] = "yellow"
        else:
            sev["ks"] = "green"

    # Detector 2 — PSI
    psi = population_stability_index(baseline, live, n_buckets=psi_n_buckets)
    if psi is not None:
        sev["psi"] = psi_severity(psi)

    # Detector 3 — mean-shift in baseline-σ units
    if baseline.size and live.size:
        bstd = float(baseline.std(ddof=0))
        if bstd > 0.0 and math.isfinite(bstd):
            shift = abs(float(live.mean()) - float(baseline.mean())) / bstd
            if shift >= 2 * MEAN_SHIFT_FIRE_SIGMA:
                sev["mean_shift"] = "red"
            elif shift >= MEAN_SHIFT_FIRE_SIGMA:
                sev["mean_shift"] = "yellow"
            else:
                sev["mean_shift"] = "green"

    # Detector 4 — variance ratio outside [VAR_RATIO_LOW, VAR_RATIO_HIGH]
    if baseline.size > 1 and live.size > 1:
        bstd = float(baseline.std(ddof=0))
        lstd = float(live.std(ddof=0))
        if bstd > 0.0 and lstd > 0.0:
            ratio = lstd / bstd
            if ratio < VAR_RATIO_LOW or ratio > VAR_RATIO_HIGH:
                sev["var_ratio"] = "red"
            elif ratio < VAR_RATIO_LOW * 1.4 or ratio > VAR_RATIO_HIGH / 1.4:
                # Soft band just inside the fire bracket → yellow.
                sev["var_ratio"] = "yellow"
            else:
                sev["var_ratio"] = "green"

    return sev


def _aggregate_metric_severity(
    detectors: dict[str, DriftSeverity | None],
    *,
    consensus_min: int,
) -> tuple[DriftSeverity, int]:
    """Apply the consensus rule.

    Returns ``(metric_severity, fires)`` where ``fires`` counts detectors
    that emitted ``yellow`` or ``red``. ``red`` is reached when the
    consensus threshold is met; otherwise ``yellow`` if any detector
    fired, else ``green``.
    """
    fires = sum(1 for s in detectors.values() if s in ("yellow", "red"))
    if fires >= consensus_min:
        return "red", fires
    if fires > 0:
        return "yellow", fires
    return "green", fires


def compute_drift_report(
    metrics: dict[str, tuple[Sequence[float] | np.ndarray, Sequence[float] | np.ndarray]],
    *,
    p_value_yellow: float = 0.05,
    p_value_red: float = 0.01,
    psi_n_buckets: int = 10,
    consensus_min: int = 2,
    enable_consensus: bool = True,
) -> dict[str, object]:
    """Build a per-metric drift report consumed by the watchdog cron.

    ``metrics`` maps metric-name → ``(baseline_samples, live_samples)``.
    With ``enable_consensus=True`` (default) each metric is evaluated by
    all four C9 detectors (K-S, PSI, mean-shift, variance-ratio) and
    classified ``red`` only when ≥ ``consensus_min`` detectors fire
    yellow-or-red — this is the production rule the
    ``scripts.c9_threshold_replay`` tuner optimises against.

    The legacy K-S-only behaviour is reachable via
    ``enable_consensus=False`` for callers that want backwards-compatible
    semantics.
    """

    findings: list[DriftFinding] = []
    findings_dicts: list[dict[str, object]] = []
    for name, (baseline, live) in metrics.items():
        a = np.asarray(baseline, dtype=np.float64)
        b = np.asarray(live, dtype=np.float64)
        stat, p = ks_two_sample(a, b)
        psi_value = population_stability_index(a, b, n_buckets=psi_n_buckets)
        if not enable_consensus:
            if p is None:
                severity: DriftSeverity = "green"
            elif p < p_value_red:
                severity = "red"
            elif p < p_value_yellow:
                severity = "yellow"
            else:
                severity = "green"
            detectors_dict: dict[str, DriftSeverity | None] = {"ks": severity}
            fires = 1 if severity in ("yellow", "red") else 0
        else:
            detectors_dict = _detector_severities(
                a,
                b,
                p_value_yellow=p_value_yellow,
                p_value_red=p_value_red,
                psi_n_buckets=psi_n_buckets,
            )
            severity, fires = _aggregate_metric_severity(
                detectors_dict, consensus_min=consensus_min
            )

        findings.append(
            DriftFinding(
                metric=name,
                statistic=stat,
                p_value=p,
                severity=severity,
                n_baseline=int(a.size),
                n_live=int(b.size),
            )
        )
        findings_dicts.append(
            {
                "metric": name,
                "statistic": round(stat, 6),
                "p_value": (None if p is None else round(p, 6)),
                "psi": (None if psi_value is None else round(psi_value, 6)),
                "severity": severity,
                "n_baseline": int(a.size),
                "n_live": int(b.size),
                "detectors": {k: v for k, v in detectors_dict.items()},
                "consensus_fires": fires,
            }
        )

    # W5-2 (stat-review wave 5): when metrics dict is empty, the loop
    # never executes and aggregate stays "green" — a vacuous pass.
    # Guard fail-closed: no metrics → unknown drift state → yellow.
    if not findings:
        aggregate = "yellow"
    else:
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
        "consensus_min": consensus_min if enable_consensus else None,
        "enable_consensus": bool(enable_consensus),
        "findings": findings_dicts,
    }
