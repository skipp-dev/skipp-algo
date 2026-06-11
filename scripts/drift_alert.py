"""Drift detection for live trade outcomes vs backtest baseline (Sprint C9 / T2-T4).

Core helpers for the Drift-Alert sprint:

- ``ks_two_sample`` — exact Kolmogorov-Smirnov two-sample statistic + an
  asymptotic p-value, no scipy dependency
- ``population_stability_index`` — PSI score with the standard
  ``[<0.10, 0.10-0.25, >0.25]`` traffic-light bands
- ``welch_t_two_sample`` / ``brown_forsythe_two_sample`` — two-sample
  mean/scale significance tests (C9/T7 detectors 3 + 4, issue #298);
  p-values via the regularized incomplete beta function, no scipy
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
# Welch t-test (mean shift) and Brown-Forsythe (variance shift)
# ---------------------------------------------------------------------------
#
# C9/T7 (issue #298): detectors 3 + 4 of the drift consensus were
# interim effect-size rules (mean shift >= 0.3 sigma, variance ratio
# outside [0.5, 2.0]) sourced from drift-monitoring rules of thumb.
# They are replaced here by proper two-sample significance tests so the
# firing rate is controlled by an alpha level instead of an arbitrary
# effect-size cutoff:
#
# - Detector 3 -> Welch t-test (unequal-variance two-sided t), robust
#   to variance imbalance between baseline and live windows.
# - Detector 4 -> Brown-Forsythe test (Levene with median centering),
#   the robust F-test variant for scale shifts. The plain F-ratio test
#   is catastrophically non-robust to heavy tails (the synthetic
#   episode bank deliberately includes t(df=4) and lognormal families),
#   so the median-centered variant is used instead.
#
# Both p-values are computed via the regularized incomplete beta
# function (continued-fraction expansion, Numerical Recipes section 6.4)
# - pure stdlib math, no scipy dependency, mirroring the asymptotic
# K-S survival function in ``scripts/_kolmogorov.py``.


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (NR 6.4)."""

    max_iter = 300
    eps = 3e-12
    fpmin = 1e-300

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc_regularized(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b), pure stdlib."""

    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _student_t_two_sided_p(t: float, df: float) -> float | None:
    """Two-sided p-value for a Student-t statistic with ``df`` dof.

    Identity: ``p = I_{df/(df+t^2)}(df/2, 1/2)``.
    """

    if not math.isfinite(t) or not math.isfinite(df) or df <= 0.0:
        return None
    x = df / (df + t * t)
    return min(1.0, max(0.0, _betainc_regularized(df / 2.0, 0.5, x)))


def _f_sf(f: float, d1: float, d2: float) -> float | None:
    """Survival function P(F > f) for an F(d1, d2) statistic.

    Identity: ``P(F > f) = I_{d2/(d2 + d1*f)}(d2/2, d1/2)``.
    """

    if not math.isfinite(f) or f < 0.0 or d1 <= 0.0 or d2 <= 0.0:
        return None
    x = d2 / (d2 + d1 * f)
    return min(1.0, max(0.0, _betainc_regularized(d2 / 2.0, d1 / 2.0, x)))


def welch_t_two_sample(
    baseline: Sequence[float] | np.ndarray,
    live: Sequence[float] | np.ndarray,
) -> tuple[float, float | None]:
    """Welch's unequal-variance two-sample t-test (two-sided).

    Returns ``(t_statistic, p_value)``. ``p_value`` is ``None`` when
    either sample has fewer than 2 observations or the pooled standard
    error is degenerate (both samples constant).
    """

    a = np.asarray(baseline, dtype=np.float64)
    b = np.asarray(live, dtype=np.float64)
    n_a = int(a.size)
    n_b = int(b.size)
    if n_a < 2 or n_b < 2:
        return 0.0, None

    va = float(a.var(ddof=1))
    vb = float(b.var(ddof=1))
    se2 = va / n_a + vb / n_b
    if se2 <= 0.0 or not math.isfinite(se2):
        return 0.0, None

    t = (float(b.mean()) - float(a.mean())) / math.sqrt(se2)
    # Welch-Satterthwaite degrees of freedom.
    df = se2 * se2 / (
        (va / n_a) ** 2 / (n_a - 1) + (vb / n_b) ** 2 / (n_b - 1)
    )
    return float(t), _student_t_two_sided_p(t, df)


def brown_forsythe_two_sample(
    baseline: Sequence[float] | np.ndarray,
    live: Sequence[float] | np.ndarray,
) -> tuple[float, float | None]:
    """Brown-Forsythe test for equality of variances (two groups).

    Levene's test with median centering: one-way ANOVA F on the
    absolute deviations from each group's median. Robust to heavy
    tails, unlike the plain F-ratio test. Returns ``(F_statistic,
    p_value)`` with ``p_value=None`` when either sample has fewer than
    2 observations or the within-group spread is degenerate.
    """

    a = np.asarray(baseline, dtype=np.float64)
    b = np.asarray(live, dtype=np.float64)
    n_a = int(a.size)
    n_b = int(b.size)
    if n_a < 2 or n_b < 2:
        return 0.0, None

    z_a = np.abs(a - np.median(a))
    z_b = np.abs(b - np.median(b))
    mean_za = float(z_a.mean())
    mean_zb = float(z_b.mean())
    n_total = n_a + n_b
    grand = (n_a * mean_za + n_b * mean_zb) / n_total

    ss_between = n_a * (mean_za - grand) ** 2 + n_b * (mean_zb - grand) ** 2
    ss_within = float(((z_a - mean_za) ** 2).sum()) + float(
        ((z_b - mean_zb) ** 2).sum()
    )
    if ss_within <= 0.0 or not math.isfinite(ss_within):
        return 0.0, None

    d1 = 1.0  # k - 1 with k = 2 groups
    d2 = float(n_total - 2)
    f = (ss_between / d1) / (ss_within / d2)
    return float(f), _f_sf(f, d1, d2)


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


# Detector-3 / Detector-4 (C9/T7, issue #298 — structural part landed
# 2026-06-11; threshold finalisation still OPEN, see NOTE below).
#
# The interim effect-size rules (mean shift >= 0.3 sigma of baseline;
# variance ratio outside [0.5, 2.0]) were replaced by two-sample
# significance tests:
#
# - Detector 3 — Welch t-test (two-sided) on the mean. Severity uses
#   the same ``p_value_yellow`` / ``p_value_red`` ladder as the K-S
#   detector so the consensus stays on a single alpha scale.
# - Detector 4 — Brown-Forsythe (median-centered Levene) on the scale.
#   Same severity ladder.
#
# Alpha levels were validated against the mixed-distribution synthetic
# episode bank in ``scripts/c9_threshold_replay.py`` (Gaussian +
# t(df=4) + lognormal); see ``docs/c9_threshold_tuning.md`` for the
# grid results. NOTE: the alphas are *synthetic-tuned* — re-tune
# against >= 90 days of live outcomes once the C12 trigger flips GREEN
# (tracked by ``tests/test_c9_threshold_finalisation_anchor.py``).


def _p_value_severity(
    p: float | None, *, p_yellow: float, p_red: float
) -> DriftSeverity | None:
    """Shared p-value → severity ladder for the K-S/Welch-t/BF detectors."""

    if p is None:
        return None
    if p < p_red:
        return "red"
    if p < p_yellow:
        return "yellow"
    return "green"


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
    sev["ks"] = _p_value_severity(p, p_yellow=p_value_yellow, p_red=p_value_red)

    # Detector 2 — PSI
    psi = population_stability_index(baseline, live, n_buckets=psi_n_buckets)
    if psi is not None:
        sev["psi"] = psi_severity(psi)

    # Detector 3 — Welch t-test on the mean (two-sided).
    # Guard: a zero-variance baseline disables detectors 3 + 4 (pinned
    # invariant — see tests/test_c9_episode_fires_invariants_property.py).
    if baseline.size > 1 and live.size > 1:
        bstd = float(baseline.std(ddof=0))
        if bstd > 0.0 and math.isfinite(bstd):
            _t, p_t = welch_t_two_sample(baseline, live)
            sev["mean_shift"] = _p_value_severity(
                p_t, p_yellow=p_value_yellow, p_red=p_value_red
            )

    # Detector 4 — Brown-Forsythe on the scale.
    # Guard: degenerate baseline OR live disables the detector.
    if baseline.size > 1 and live.size > 1:
        bstd = float(baseline.std(ddof=0))
        lstd = float(live.std(ddof=0))
        if bstd > 0.0 and lstd > 0.0:
            _f, p_f = brown_forsythe_two_sample(baseline, live)
            sev["var_ratio"] = _p_value_severity(
                p_f, p_yellow=p_value_yellow, p_red=p_value_red
            )

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
    p_value_yellow: float = 0.025,
    p_value_red: float = 0.005,
    psi_n_buckets: int = 10,
    consensus_min: int = 2,
    enable_consensus: bool = True,
) -> dict[str, object]:
    """Build a per-metric drift report consumed by the watchdog cron.

    ``metrics`` maps metric-name → ``(baseline_samples, live_samples)``.
    With ``enable_consensus=True`` (default) each metric is evaluated by
    all four C9 detectors (K-S, PSI, Welch-t, Brown-Forsythe) and
    classified ``red`` only when ≥ ``consensus_min`` detectors fire
    yellow-or-red — this is the production rule the
    ``scripts.c9_threshold_replay`` tuner optimises against.

    Default alpha ladder (C9/T7, issue #298, 2026-06-11): ``p_red=0.005``
    / ``p_yellow=0.025`` won the replay grid on BOTH the Gaussian-only
    and the mixed-distribution synthetic banks (TPR 0.80/0.90, FPR
    0.03/0.07); the previous ``0.01/0.05`` default failed the FPR<0.10
    acceptance bar on the mixed bank (FPR 0.12) once detectors 3+4
    became p-value tests. Synthetic-tuned — re-tune against ≥ 90 days of
    live outcomes when the C12 trigger flips GREEN (see
    ``docs/c9_threshold_tuning.md``).

    The legacy K-S-only DETECTOR SET is reachable via
    ``enable_consensus=False``. Note this does NOT restore the pre-#298
    behaviour wholesale: the default alpha ladder changed in the same PR
    (``0.01/0.05`` → ``0.005/0.025``) and applies to the KS-only mode
    too — callers that want the old thresholds must pass
    ``p_value_red=0.01, p_value_yellow=0.05`` explicitly.
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
