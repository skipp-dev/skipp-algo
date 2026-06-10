#!/usr/bin/env python3
"""OV7 — Compare measurement benchmark results between A/B experiment arms.

Reads two sets of benchmark artifacts (one per arm) and produces a
side-by-side KPI comparison table (Markdown + JSON).

Usage
-----
::

    python scripts/run_ab_comparison.py \\
        --control-dir  artifacts/ci/measurement_benchmark_control \\
        --treatment-dir artifacts/ci/measurement_benchmark_treatment \\
        --experiment-name news-benzinga-uplift \\
        --output-dir artifacts/reports

Output
------
- ``ab_comparison.md``  — human-readable diff table
- ``ab_comparison.json`` — machine-readable comparison digest
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# Re-use the report helpers from the performance report generator.
from scripts.generate_performance_report import (
    PairReport,
    _aggregate,
    _grade,
    load_benchmark,
)
from scripts.smc_atomic_write import atomic_write_text
from scripts.smc_sprt_stop_rule import SPRTConfig, terminal_decision


def _delta(treatment: float, control: float) -> str:
    """Format delta as +/- with 4 decimals."""
    d = treatment - control
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.4f}"


def _better_arrow(metric: str, treatment: float, control: float) -> str:
    """Return ↑ / ↓ / = indicating whether treatment is better."""
    # For Brier / ECE: lower is better.  For hit_rate: higher is better.
    if metric in ("hit_rate_pct",):
        if treatment > control:
            return "↑ better"
        if treatment < control:
            return "↓ worse"
        return "="
    # Lower-is-better metrics.
    if treatment < control:
        return "↑ better"
    if treatment > control:
        return "↓ worse"
    return "="


def _dict_to_pair(d: dict[str, Any]) -> PairReport:
    """Convert a plain dict (e.g. from tests) into a PairReport."""
    return PairReport(
        symbol=d.get("symbol", ""),
        timeframe=d.get("timeframe", ""),
        n_events=int(d.get("n_events", 0)),
        brier=float(d.get("brier", float("nan"))),
        log_score=float(d.get("log_score", float("nan"))),
        hit_rate=float(d.get("hit_rate_pct", d.get("hit_rate", float("nan")))),
        calibration_method=str(d.get("calibration_method", "identity")),
        calibrated_brier=float(d.get("calibrated_brier", float("nan"))),
        calibrated_ece=float(d.get("calibrated_ece", float("nan"))),
        raw_ece=float(d.get("raw_ece", float("nan"))),
        families_present=d.get("families_present", []),
        family_metrics=d.get("family_metrics", {}),
        ensemble_score=float(d.get("ensemble_score", float("nan"))),
        ensemble_tier=str(d.get("ensemble_tier", "")),
        stratified_dimensions=d.get("stratified_dimensions", []),
        populated_buckets=int(d.get("populated_buckets", 0)),
        warnings=d.get("warnings", []),
        contextual_best_brier_dim=str(d.get("contextual_best_brier_dim", "")),
        contextual_best_ece_dim=str(d.get("contextual_best_ece_dim", "")),
    )


def compare(
    control_pairs: list[dict[str, Any]],
    treatment_pairs: list[dict[str, Any]],
    experiment_name: str,
    *,
    control_ledgers: Sequence[Sequence[tuple[str, float, bool]]] | None = None,
    treatment_ledgers: Sequence[Sequence[tuple[str, float, bool]]] | None = None,
    enable_calibration_fdr: bool = False,
    calibration_fdr_B: int = 2000,
    calibration_fdr_seed: int = 42,
    sprt_config: SPRTConfig | None = None,
) -> dict[str, Any]:
    """Build the comparison digest.

    When ``enable_calibration_fdr`` is True and per-event ledgers for both
    arms are provided, an additional ``digest["fdr_calibration"]`` block
    is computed (permutation-based BH-FDR over family×{brier,ece}). This
    layer is **advisory** — it never alters the Promote/Hold/Rollback
    recommendation. See :func:`_calibration_fdr_layer` for the contract.

    ``sprt_config`` overrides the module-default Wald parameters
    (``SPRT_P0``/``SPRT_P1``/...). The F2 promotion gate passes the
    pre-registered values from the experiment spec here so the spec
    stays the single source of truth (2026-06-10 audit: the spec's
    recalibrated p0/p1 were silently ignored before this parameter
    existed).
    """
    ctrl_reports = [_dict_to_pair(p) for p in control_pairs]
    treat_reports = [_dict_to_pair(p) for p in treatment_pairs]
    ctrl_agg = _aggregate(ctrl_reports)
    treat_agg = _aggregate(treat_reports)

    # Map metric keys to AggregateReport attribute names.
    _attr_map = {
        "brier": "avg_brier",
        "calibrated_brier": "avg_calibrated_brier",
        "calibrated_ece": "avg_calibrated_ece",
        "hit_rate_pct": "avg_hit_rate",
    }

    rows: list[dict[str, Any]] = []
    for key in ("brier", "calibrated_brier", "calibrated_ece", "hit_rate_pct"):
        attr = _attr_map[key]
        c = getattr(ctrl_agg, attr, 0.0)
        t = getattr(treat_agg, attr, 0.0)
        rows.append({
            "metric": key,
            "control": round(c, 4),
            "treatment": round(t, 4),
            "delta": round(t - c, 4),
            "direction": _better_arrow(key, t, c),
        })

    decision = decide_recommendation(rows)

    sprt = _sprt_decision(ctrl_agg, treat_agg, config=sprt_config)

    fdr = _family_fdr_layer(control_pairs, treatment_pairs)

    fdr_calibration = _calibration_fdr_layer(
        control_ledgers=control_ledgers,
        treatment_ledgers=treatment_ledgers,
        enabled=enable_calibration_fdr,
        B=calibration_fdr_B,
        seed=calibration_fdr_seed,
    )

    return {
        "experiment": experiment_name,
        "control_pairs": len(control_pairs),
        "treatment_pairs": len(treatment_pairs),
        "control_grade": _grade(getattr(ctrl_agg, "avg_calibrated_brier", 1.0)),
        "treatment_grade": _grade(getattr(treat_agg, "avg_calibrated_brier", 1.0)),
        "metrics": rows,
        "recommendation": decision["recommendation"],
        "recommendation_reason": decision["reason"],
        "kpi_thresholds": decision["kpi_thresholds"],
        "sprt": sprt,
        "fdr": fdr,
        "fdr_calibration": fdr_calibration,
    }


# ── S-2: Per-family Benjamini-Hochberg FDR (advisory) ──────────────────────


# Per-family q-value cap used by the BH procedure. ADR-0002 §6 placeholder
# binds operators to a single global FDR control level; 0.05 matches the
# SPRT alpha already in use so the two layers stay coherent. Bumping this
# constant downstream affects ONLY the advisory rejection flag, not the
# Promote/Hold/Rollback decision.
FDR_Q = 0.05


def benjamini_hochberg(pvals: list[float], q: float = FDR_Q) -> dict[str, Any]:
    """Benjamini-Hochberg FDR control on a list of p-values.

    Implements the classical Benjamini-Hochberg step-up procedure
    (B&H 1995): orders p-values ascending, finds the largest rank ``k``
    where ``p_(k) <= k/m * q``, and rejects all hypotheses with rank ≤ k.

    Returns a dict with:
      * ``rejected`` — list[bool] in the *original* input order.
      * ``adjusted`` — list[float] of BH-adjusted p-values
        (``p_(k) * m / k``, monotonised), in original input order.
      * ``threshold`` — the largest p-value that passes BH at ``q``,
        or ``None`` if no rejections.
      * ``q`` — the cap used.

    Pure stdlib (no scipy/statsmodels) so this stays in the lean
    measurement-runtime contract.
    """
    m = len(pvals)
    if m == 0:
        return {"rejected": [], "adjusted": [], "threshold": None, "q": q}
    # Validate inputs (advisory layer must never raise on already-clamped data).
    sanitized = [max(0.0, min(1.0, float(p))) for p in pvals]
    indexed = sorted(range(m), key=lambda i: sanitized[i])
    sorted_p = [sanitized[i] for i in indexed]
    # Step-up: largest k with p_(k) <= (k/m) * q.
    threshold_rank = -1
    for k_minus_1, p in enumerate(sorted_p):
        rank = k_minus_1 + 1  # 1-indexed
        if p <= (rank / m) * q:
            threshold_rank = rank
    threshold_p = sorted_p[threshold_rank - 1] if threshold_rank > 0 else None
    # BH-adjusted p-values: monotone non-decreasing from largest to smallest.
    adj_sorted = [0.0] * m
    running_min = 1.0
    for i in range(m - 1, -1, -1):
        rank = i + 1
        adj = sorted_p[i] * m / rank
        running_min = min(running_min, adj)
        adj_sorted[i] = min(running_min, 1.0)
    rejected_sorted = [
        (i + 1) <= threshold_rank for i in range(m)
    ] if threshold_rank > 0 else [False] * m
    # Map back to original order.
    adjusted = [0.0] * m
    rejected = [False] * m
    for sorted_idx, orig_idx in enumerate(indexed):
        adjusted[orig_idx] = adj_sorted[sorted_idx]
        rejected[orig_idx] = rejected_sorted[sorted_idx]
    return {
        "rejected": rejected,
        "adjusted": adjusted,
        "threshold": threshold_p,
        "q": q,
    }


def _normal_cdf(x: float) -> float:
    """Standard-normal CDF via math.erf (stdlib only)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _two_proportion_z_pvalue(
    *,
    k_treat: int,
    n_treat: int,
    k_ctrl: int,
    n_ctrl: int,
) -> float | None:
    """One-sided pooled-variance z-test p-value for treatment > control.

    Returns ``None`` when either arm has zero events or pooled variance is
    degenerate (both arms have identical zero/all-hit rates) — caller must
    skip such families from the BH input list to keep ranks well-defined.
    """
    if n_treat <= 0 or n_ctrl <= 0:
        return None
    p_treat = k_treat / n_treat
    p_ctrl = k_ctrl / n_ctrl
    p_pool = (k_treat + k_ctrl) / (n_treat + n_ctrl)
    if math.isclose(p_pool, 0.0, abs_tol=1e-12) or math.isclose(p_pool, 1.0, abs_tol=1e-12):
        return None
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_treat + 1.0 / n_ctrl))
    if math.isclose(se, 0.0, abs_tol=1e-12):
        return None
    z = (p_treat - p_ctrl) / se
    # One-sided: p = P(Z > z)
    return max(0.0, min(1.0, 1.0 - _normal_cdf(z)))


def _family_fdr_layer(
    control_pairs: list[dict[str, Any]],
    treatment_pairs: list[dict[str, Any]],
    *,
    q: float = FDR_Q,
) -> dict[str, Any]:
    """Build the per-family BH-FDR advisory layer.

    For each family present in *both* arms with non-zero event counts,
    computes a one-sided two-proportion z-test p-value (treatment > control
    on hit rate), then applies Benjamini-Hochberg at ``q`` to control the
    family-wise false-discovery rate.

    The output is **advisory only**: it does not alter the
    Promote/Hold/Rollback decision. Operators inspect the rejection set to
    distinguish "treatment beats control on family X with FDR-controlled
    confidence" from "treatment looks better on family X but the difference
    is not significant after correcting for testing K families".
    """
    def _aggregate_family_events(
        pairs: list[dict[str, Any]],
    ) -> dict[str, tuple[int, int]]:
        agg: dict[str, tuple[int, int]] = {}
        for pair in pairs:
            for fam, fm in (pair.get("family_metrics") or {}).items():
                n = int(fm.get("n_events", 0) or 0)
                hr = float(fm.get("hit_rate", 0.0) or 0.0)
                # hit_rate may be stored as fraction OR percentage
                # (legacy artifacts). Auto-detect: values > 1.0 are %.
                if hr > 1.0:
                    hr = hr / 100.0
                k = round(n * max(0.0, min(1.0, hr)))
                prev_n, prev_k = agg.get(fam, (0, 0))
                agg[fam] = (prev_n + n, prev_k + k)
        return agg

    ctrl_fam = _aggregate_family_events(control_pairs)
    treat_fam = _aggregate_family_events(treatment_pairs)
    common = sorted(set(ctrl_fam) & set(treat_fam))

    families: list[dict[str, Any]] = []
    pvals: list[float] = []
    p_indices: list[int] = []  # index into ``families`` for each p-value
    for fam in common:
        n_ctrl, k_ctrl = ctrl_fam[fam]
        n_treat, k_treat = treat_fam[fam]
        p = _two_proportion_z_pvalue(
            k_treat=k_treat, n_treat=n_treat, k_ctrl=k_ctrl, n_ctrl=n_ctrl
        )
        entry = {
            "family": fam,
            "n_control": n_ctrl,
            "n_treatment": n_treat,
            "hit_rate_control": round(k_ctrl / n_ctrl, 4) if n_ctrl else None,
            "hit_rate_treatment": round(k_treat / n_treat, 4) if n_treat else None,
            "p_value": None if p is None else round(p, 6),
            "rejected": False,
            "adjusted_p_value": None,
            "skipped_reason": None if p is not None else "degenerate_or_empty",
        }
        if p is not None:
            p_indices.append(len(families))
            pvals.append(p)
        families.append(entry)

    bh = benjamini_hochberg(pvals, q=q)
    for slot, fam_idx in enumerate(p_indices):
        families[fam_idx]["rejected"] = bool(bh["rejected"][slot])
        families[fam_idx]["adjusted_p_value"] = round(float(bh["adjusted"][slot]), 6)

    rejected_families = [e["family"] for e in families if e["rejected"]]
    return {
        "method": "benjamini_hochberg",
        "q": q,
        "tested_families": len(pvals),
        "skipped_families": len(families) - len(pvals),
        "rejected_families": rejected_families,
        "threshold_p_value": (
            round(float(bh["threshold"]), 6) if bh["threshold"] is not None else None
        ),
        "families": families,
    }


# ── S-2 follow-up: Bootstrap-FDR for calibration metrics (advisory) ────────


# Bootstrap / permutation parameters for the calibration-FDR layer.
# B=2000 is the standard P0 budget; raise via CLI for sharper p-values
# (compute scales O(B * total_events_per_cell)). Seed is fixed so reports
# are byte-reproducible — override only for sanity-rerun checks.
BOOTSTRAP_B = 2000
BOOTSTRAP_SEED = 42
BOOTSTRAP_FDR_Q = FDR_Q
ECE_BIN_COUNT = 10
# Permutation granularity is unreliable below this per-arm event count.
# Below the threshold we skip the cell with reason="insufficient_events".
MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP = 30


def _metric_brier(events: Sequence[tuple[float, bool]]) -> float:
    """Brier score: mean((p - o)^2). NaN on empty input."""
    if not events:
        return float("nan")
    return sum((p - (1.0 if o else 0.0)) ** 2 for p, o in events) / len(events)


def _metric_ece(
    events: Sequence[tuple[float, bool]], bins: int = ECE_BIN_COUNT
) -> float:
    """Expected Calibration Error: weighted |avg_prob - avg_outcome| per bin.

    Bin assignment matches ``smc_core/scoring._bucket_index`` (10 equal-width
    bins on [0, 1], probabilities clipped). NaN on empty input.
    """
    if not events:
        return float("nan")
    buckets: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for p, o in events:
        p_clip = min(max(float(p), 0.0), 1.0)
        idx = min(int(p_clip * bins), bins - 1)
        buckets[idx].append((p_clip, 1.0 if o else 0.0))
    n = len(events)
    ece = 0.0
    for bucket in buckets.values():
        w = len(bucket) / n
        mp = sum(p for p, _ in bucket) / len(bucket)
        mo = sum(o for _, o in bucket) / len(bucket)
        ece += w * abs(mp - mo)
    return ece


_METRIC_FNS: dict[str, Callable[[Sequence[tuple[float, bool]]], float]] = {
    "brier": _metric_brier,
    "ece": _metric_ece,
}


def _permutation_p_delta_metric(
    *,
    treatment: Sequence[tuple[float, bool]],
    control: Sequence[tuple[float, bool]],
    metric_fn: Callable[[Sequence[tuple[float, bool]]], float],
    lower_is_better: bool = True,
    B: int = BOOTSTRAP_B,
    seed: int = BOOTSTRAP_SEED,
) -> float | None:
    """Two-sample permutation p-value on a prediction-accuracy metric.

    One-sided H1 for lower-is-better metrics:
        H1: metric(treatment) < metric(control)  (treatment strictly better)
    For upper-is-better metrics, the inequality flips.

    Uses classical Fisher permutation (resampling labels without
    replacement from the pooled sample) and the Phipson-Smyth
    ``(r + 1) / (B + 1)`` correction (Phipson & Smyth 2010) so the
    returned p-value is never exactly 0 — preventing downstream
    ``log(p)`` from diverging.

    Returns ``None`` if either arm is empty or below
    :data:`MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP`.
    """
    n_t = len(treatment)
    n_c = len(control)
    if n_t == 0 or n_c == 0:
        return None
    if n_t < MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP or n_c < MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP:
        return None
    obs_delta = metric_fn(treatment) - metric_fn(control)
    if math.isnan(obs_delta):
        return None

    rng = random.Random(seed)
    pooled = list(treatment) + list(control)
    m = len(pooled)
    indices = list(range(m))

    at_least_as_extreme = 0
    for _ in range(B):
        rng.shuffle(indices)
        perm_t = [pooled[i] for i in indices[:n_t]]
        perm_c = [pooled[i] for i in indices[n_t:]]
        perm_delta = metric_fn(perm_t) - metric_fn(perm_c)
        if lower_is_better:
            if perm_delta <= obs_delta:
                at_least_as_extreme += 1
        else:
            if perm_delta >= obs_delta:
                at_least_as_extreme += 1
    # Phipson-Smyth correction.
    return (at_least_as_extreme + 1) / (B + 1)


def _aggregate_ledger_by_family(
    ledgers: Sequence[Sequence[tuple[str, float, bool]]],
) -> dict[str, list[tuple[float, bool]]]:
    """Concatenate per-pair ledgers into per-family ``(prob, outcome)`` lists."""
    agg: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for ledger in ledgers:
        for row in ledger:
            family, prob, outcome = row[0], float(row[1]), bool(row[2])
            agg[family].append((prob, outcome))
    return agg


def _calibration_fdr_layer(
    *,
    control_ledgers: Sequence[Sequence[tuple[str, float, bool]]] | None,
    treatment_ledgers: Sequence[Sequence[tuple[str, float, bool]]] | None,
    enabled: bool,
    B: int = BOOTSTRAP_B,
    seed: int = BOOTSTRAP_SEED,
    q: float = BOOTSTRAP_FDR_Q,
    metrics: Sequence[str] = ("brier", "ece"),
) -> dict[str, Any]:
    """Permutation-based BH-FDR layer over family×{brier,ece} cells.

    Tests treatment-improves-on-control (lower-is-better) per cell, then
    applies Benjamini-Hochberg jointly over all tested cells (4 families ×
    2 metrics = 8 tests in the typical SMC setup).

    The layer is **advisory only**: the result is surfaced as
    ``digest["fdr_calibration"]`` and as a section in the markdown report
    but never alters the Promote/Hold/Rollback recommendation, the SPRT
    decision, or the hit-rate FDR layer (``digest["fdr"]``). This contract
    is asserted by the regression test in
    ``tests/test_run_ab_comparison_calibration_fdr.py``.

    Test runs against post-calibration probabilities as recorded in the
    event ledger; the calibrator itself is **not** re-fit per permutation
    (P0 design — see design memo §3.2 Option A). Output ``notes`` field
    documents this conditioning.
    """
    if not enabled:
        return {"skipped_reason": "disabled", "method": "permutation_bh"}
    if control_ledgers is None or treatment_ledgers is None:
        return {"skipped_reason": "ledger_not_provided", "method": "permutation_bh"}

    ctrl_by_fam = _aggregate_ledger_by_family(control_ledgers)
    treat_by_fam = _aggregate_ledger_by_family(treatment_ledgers)
    common_families = sorted(set(ctrl_by_fam) & set(treat_by_fam))

    cells: list[dict[str, Any]] = []
    pvals: list[float] = []
    p_indices: list[int] = []  # index into ``cells`` for each tested p-value

    for fam_idx, family in enumerate(common_families):
        ctrl_events = ctrl_by_fam[family]
        treat_events = treat_by_fam[family]
        for metric_name in metrics:
            metric_fn = _METRIC_FNS[metric_name]
            n_c = len(ctrl_events)
            n_t = len(treat_events)
            mc = metric_fn(ctrl_events)
            mt = metric_fn(treat_events)
            # Per-cell seed: derive deterministically so adding a family
            # does not shift seeds of pre-existing cells.
            cell_seed = seed + 1000 * fam_idx + (1 if metric_name == "ece" else 0)
            p = _permutation_p_delta_metric(
                treatment=treat_events,
                control=ctrl_events,
                metric_fn=metric_fn,
                lower_is_better=True,
                B=B,
                seed=cell_seed,
            )
            entry: dict[str, Any] = {
                "family": family,
                "metric": metric_name,
                "n_control": n_c,
                "n_treatment": n_t,
                "metric_control": (
                    None if math.isnan(mc) else round(mc, 6)
                ),
                "metric_treatment": (
                    None if math.isnan(mt) else round(mt, 6)
                ),
                "delta": (
                    None if (math.isnan(mc) or math.isnan(mt)) else round(mt - mc, 6)
                ),
                "p_value": None if p is None else round(p, 6),
                "adjusted_p_value": None,
                "rejected": False,
                "lower_is_better": True,
                "skipped_reason": (
                    None if p is not None else "insufficient_events_for_bootstrap"
                ),
            }
            if p is not None:
                p_indices.append(len(cells))
                pvals.append(p)
            cells.append(entry)

    bh = benjamini_hochberg(pvals, q=q)
    for slot, cell_idx in enumerate(p_indices):
        cells[cell_idx]["rejected"] = bool(bh["rejected"][slot])
        cells[cell_idx]["adjusted_p_value"] = round(float(bh["adjusted"][slot]), 6)

    rejected_cells = [
        {"family": c["family"], "metric": c["metric"]}
        for c in cells
        if c["rejected"]
    ]

    return {
        "method": "permutation_bh",
        "q": q,
        "B": B,
        "seed": seed,
        "metrics_tested": list(metrics),
        "tested_cells": len(pvals),
        "skipped_cells": len(cells) - len(pvals),
        "rejected_cells": rejected_cells,
        "threshold_p_value": (
            round(float(bh["threshold"]), 6) if bh["threshold"] is not None else None
        ),
        "min_events_per_arm": MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP,
        "notes": (
            "Test evaluates post-calibration probabilities as recorded in "
            "event_ledger. Calibrator is not re-fit per permutation; results "
            "are conditional on observed calibrator fit."
        ),
        "cells": cells,
    }


# ── G3/F2 SPRT terminal decision ───────────────────────────────────────────


# Default Wald SPRT parameters. p0/p1 follow plan §2.4 G3: minimum-
# detectable effect of +5 percentage points hit-rate improvement over a
# 0.55 baseline (the lifetime-corpus median across families). alpha=0.05,
# beta=0.20 are the conventional gate settings. These are FALLBACK values
# for callers that do not pass ``sprt_config`` to :func:`compare`; the F2
# promotion gate overrides them with the spec's pre-registered parameters
# (2026-06-10 audit — see docs/DECISIONS.md
# §2026-06-10 f2-dual-arm-raw-score-shadowing).
SPRT_P0 = 0.55
SPRT_P1 = 0.60
SPRT_ALPHA = 0.05
SPRT_BETA = 0.20


def _sprt_decision(
    ctrl_agg: Any,
    treat_agg: Any,
    *,
    config: SPRTConfig | None = None,
) -> dict[str, Any]:
    """Compute the terminal SPRT decision for the treatment arm.

    Single-arm Wald SPRT: tests treatment hit rate against the *fixed*
    baseline ``p0`` (lifetime-corpus median), not against the
    in-experiment control. This matches the F2 promotion-gate semantics
    in ``docs/f2_contextual_promotion_decision_2026-04-21.md`` step 3.

    ``config`` defaults to the module constants for backwards
    compatibility; the F2 gate passes the spec's pre-registered
    parameters instead (see :func:`compare`).

    Returns a structured dict with the decision, totals, and the
    resolved Wald bounds. Hit-rate values arrive as percentages
    (0–100); we convert to fractions before deriving k.
    """
    n = int(getattr(treat_agg, "total_events", 0) or 0)
    hr_pct = float(getattr(treat_agg, "avg_hit_rate", 0.0) or 0.0)
    # avg_hit_rate is in percent; clamp into [0, 100] before conversion.
    hr_pct = max(0.0, min(100.0, hr_pct))
    k = round(n * hr_pct / 100.0)

    if config is None:
        config = SPRTConfig(
            p0=SPRT_P0,
            p1=SPRT_P1,
            alpha=SPRT_ALPHA,
            beta=SPRT_BETA,
        )
    state, decision = terminal_decision(n=n, k=k, config=config)
    return {
        "decision": decision,
        "n": state.n,
        "k": state.k,
        "hit_rate": round(state.hit_rate, 4),
        "llr": round(state.llr, 4),
        "wald_upper": round(config.upper_bound, 4),
        "wald_lower": round(config.lower_bound, 4),
        "config": {
            "p0": config.p0,
            "p1": config.p1,
            "alpha": config.alpha,
            "beta": config.beta,
        },
        # Mirror the control arm's totals so the report is self-contained.
        "control_n": int(getattr(ctrl_agg, "total_events", 0) or 0),
        "control_hit_rate": round(
            float(getattr(ctrl_agg, "avg_hit_rate", 0.0) or 0.0) / 100.0, 4
        ),
    }


# ── Promotion decision (ENG-WS4-04) ────────────────────────────────────────


# KPI thresholds binding the Promote / Hold / Rollback decision.
# Lower-is-better metrics (brier, calibrated_brier, calibrated_ece):
#   * PROMOTE if treatment improves both calibrated_brier AND calibrated_ece
#     by at least PROMOTE_IMPROVEMENT, AND hit_rate does not regress by
#     more than HIT_RATE_REGRESSION_TOLERANCE.
#   * ROLLBACK if either calibrated_brier OR calibrated_ece regresses by
#     more than ROLLBACK_REGRESSION.
#   * HOLD otherwise.
PROMOTE_IMPROVEMENT = 0.005
ROLLBACK_REGRESSION = 0.010
HIT_RATE_REGRESSION_TOLERANCE = 1.0  # percentage points


def _row_by_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("metric") == key:
            return row
    return None


def decide_recommendation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Map a comparison-metric table to a Promote/Hold/Rollback decision.

    DoD: 'Comparison-Output enthaelt Promote/Hold/Rollback-Empfehlung'
    and 'die Entscheidung ist an klare KPI-Schwellen gebunden'.
    """
    cb = _row_by_metric(rows, "calibrated_brier") or {}
    ce = _row_by_metric(rows, "calibrated_ece") or {}
    hr = _row_by_metric(rows, "hit_rate_pct") or {}

    cb_delta = float(cb.get("delta") or 0.0)  # lower = better
    ce_delta = float(ce.get("delta") or 0.0)
    hr_delta = float(hr.get("delta") or 0.0)  # higher = better

    thresholds = {
        "promote_improvement": PROMOTE_IMPROVEMENT,
        "rollback_regression": ROLLBACK_REGRESSION,
        "hit_rate_regression_tolerance": HIT_RATE_REGRESSION_TOLERANCE,
    }

    # Rollback first — a regression on either calibration metric trumps.
    if cb_delta > ROLLBACK_REGRESSION or ce_delta > ROLLBACK_REGRESSION:
        return {
            "recommendation": "rollback",
            "reason": (
                f"calibrated_brier delta {cb_delta:+.4f} or calibrated_ece delta "
                f"{ce_delta:+.4f} exceeds rollback regression "
                f"{ROLLBACK_REGRESSION:+.4f}"
            ),
            "kpi_thresholds": thresholds,
        }

    # Promote when both calibration metrics improve materially AND hit_rate
    # does not regress more than the tolerance.
    promote_cb = cb_delta <= -PROMOTE_IMPROVEMENT
    promote_ce = ce_delta <= -PROMOTE_IMPROVEMENT
    hit_rate_ok = hr_delta >= -HIT_RATE_REGRESSION_TOLERANCE
    if promote_cb and promote_ce and hit_rate_ok:
        return {
            "recommendation": "promote",
            "reason": (
                f"calibrated_brier {cb_delta:+.4f} and calibrated_ece {ce_delta:+.4f} "
                f"both improve by ≥{PROMOTE_IMPROVEMENT} and hit_rate delta "
                f"{hr_delta:+.2f}pp within tolerance {HIT_RATE_REGRESSION_TOLERANCE}pp"
            ),
            "kpi_thresholds": thresholds,
        }

    return {
        "recommendation": "hold",
        "reason": (
            f"deltas (calibrated_brier={cb_delta:+.4f}, calibrated_ece={ce_delta:+.4f}, "
            f"hit_rate={hr_delta:+.2f}pp) do not meet promote thresholds and stay "
            f"within rollback bounds"
        ),
        "kpi_thresholds": thresholds,
    }


def render_comparison(digest: dict[str, Any]) -> str:
    """Render the comparison digest as Markdown."""
    lines: list[str] = []
    lines.append(f"# A/B Comparison: {digest['experiment']}")
    lines.append("")
    lines.append("| Arm | Pairs | Grade |")
    lines.append("|-----|------:|-------|")
    lines.append(f"| Control   | {digest['control_pairs']} | {digest['control_grade']} |")
    lines.append(f"| Treatment | {digest['treatment_pairs']} | {digest['treatment_grade']} |")
    lines.append("")
    lines.append("## KPI Comparison")
    lines.append("")
    lines.append("| Metric | Control | Treatment | Delta | Direction |")
    lines.append("|--------|--------:|----------:|------:|-----------|")
    for row in digest["metrics"]:
        lines.append(
            f"| {row['metric']} | {row['control']:.4f} | "
            f"{row['treatment']:.4f} | {_delta(row['treatment'], row['control'])} | "
            f"{row['direction']} |"
        )
    lines.append("")
    # ENG-WS4-04: Promote / Hold / Rollback decision section.
    rec = str(digest.get("recommendation") or "hold").upper()
    reason = str(digest.get("recommendation_reason") or "")
    thresholds = digest.get("kpi_thresholds") or {}
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"**Decision:** `{rec}`")
    lines.append("")
    if reason:
        lines.append(f"_{reason}_")
        lines.append("")
    if thresholds:
        lines.append("KPI thresholds:")
        for key, val in thresholds.items():
            lines.append(f"- `{key}` = {val}")
        lines.append("")
    sprt = digest.get("sprt") or {}
    if sprt:
        lines.append("## SPRT Stop-Rule (G3/F2)")
        lines.append("")
        lines.append(f"**Terminal decision:** `{str(sprt.get('decision') or '').upper()}`")
        lines.append("")
        lines.append(
            f"- treatment n={sprt.get('n')}, k={sprt.get('k')}, "
            f"hit_rate={sprt.get('hit_rate')}"
        )
        lines.append(
            f"- LLR = {sprt.get('llr')} (Wald bounds: "
            f"lower={sprt.get('wald_lower')}, upper={sprt.get('wald_upper')})"
        )
        cfg = sprt.get("config") or {}
        lines.append(
            f"- config: p0={cfg.get('p0')}, p1={cfg.get('p1')}, "
            f"alpha={cfg.get('alpha')}, beta={cfg.get('beta')}"
        )
        lines.append("")
    fdr = digest.get("fdr") or {}
    if fdr and fdr.get("families"):
        lines.append("## Per-Family FDR (Benjamini-Hochberg, advisory)")
        lines.append("")
        lines.append(
            f"_q = {fdr.get('q')}, tested = {fdr.get('tested_families')}, "
            f"skipped = {fdr.get('skipped_families')}, "
            f"rejected = {len(fdr.get('rejected_families') or [])}_"
        )
        lines.append("")
        lines.append("| Family | n(C) | n(T) | HR(C) | HR(T) | p | adj. p | rejected |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|:---:|")
        for fam in fdr["families"]:
            lines.append(
                f"| {fam['family']} | {fam['n_control']} | {fam['n_treatment']} | "
                f"{fam['hit_rate_control']} | {fam['hit_rate_treatment']} | "
                f"{fam['p_value']} | {fam['adjusted_p_value']} | "
                f"{'✓' if fam['rejected'] else '·'} |"
            )
        lines.append("")
    fdr_cal = digest.get("fdr_calibration") or {}
    if fdr_cal and fdr_cal.get("cells"):
        lines.append("## Calibration FDR (Permutation-BH, advisory)")
        lines.append("")
        lines.append(
            f"_q = {fdr_cal.get('q')}, B = {fdr_cal.get('B')}, "
            f"seed = {fdr_cal.get('seed')}, tested = {fdr_cal.get('tested_cells')}, "
            f"skipped = {fdr_cal.get('skipped_cells')}, "
            f"rejected = {len(fdr_cal.get('rejected_cells') or [])}_"
        )
        lines.append("")
        lines.append(f"_{fdr_cal.get('notes', '')}_")
        lines.append("")
        lines.append(
            "| Family | Metric | n(C) | n(T) | metric(C) | metric(T) | \u0394 | p | adj. p | rejected |"
        )
        lines.append(
            "|---|---|---:|---:|---:|---:|---:|---:|---:|:---:|"
        )
        for cell in fdr_cal["cells"]:
            lines.append(
                f"| {cell['family']} | {cell['metric']} | {cell['n_control']} | "
                f"{cell['n_treatment']} | {cell['metric_control']} | "
                f"{cell['metric_treatment']} | {cell['delta']} | "
                f"{cell['p_value']} | {cell['adjusted_p_value']} | "
                f"{'✓' if cell['rejected'] else '·'} |"
            )
        lines.append("")
    return "\n".join(lines)


def _load_ledgers_for_dir(
    benchmark_dir: Path,
) -> list[list[tuple[str, float, bool]]]:
    """Load all per-pair event ledgers (events_*.jsonl) under ``benchmark_dir``.

    Returns a list of per-pair ledgers; each ledger is a list of
    ``(family, predicted_prob, outcome)`` tuples. Pairs without a ledger
    sibling produce an empty list (so per-pair indexing is preserved
    relative to ``load_benchmark``).
    """
    from smc_core.event_ledger import read_event_ledger

    ledgers: list[list[tuple[str, float, bool]]] = []
    # Sorted glob keeps order deterministic across filesystems.
    for ledger_path in sorted(benchmark_dir.rglob("events_*.jsonl")):
        rows: list[tuple[str, float, bool]] = []
        for record in read_event_ledger(ledger_path):
            family = str(record.get("family", ""))
            if not family:
                continue
            prob_raw = record.get("predicted_prob")
            if prob_raw is None:
                continue
            try:
                prob = float(prob_raw)
            except (TypeError, ValueError):
                continue
            outcome = bool(record.get("outcome", False))
            rows.append((family, prob, outcome))
        ledgers.append(rows)
    return ledgers


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare A/B benchmark arms")
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--treatment-dir", type=Path, required=True)
    parser.add_argument("--experiment-name", type=str, default="unnamed")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/reports"))
    parser.add_argument(
        "--enable-calibration-fdr",
        action="store_true",
        help=(
            "Compute permutation-based BH-FDR over family×{brier,ece} cells "
            "using per-event ledgers (events_<SYM>_<TF>.jsonl) sibling to "
            "each scoring_*.json. Advisory only — does not change the "
            "Promote/Hold/Rollback recommendation."
        ),
    )
    parser.add_argument(
        "--calibration-fdr-B",
        type=int,
        default=BOOTSTRAP_B,
        help=f"Permutation count per cell (default {BOOTSTRAP_B}).",
    )
    parser.add_argument(
        "--calibration-fdr-seed",
        type=int,
        default=BOOTSTRAP_SEED,
        help=f"Permutation seed (default {BOOTSTRAP_SEED}, fixed for reproducibility).",
    )
    args = parser.parse_args(argv)

    control_pairs = load_benchmark(args.control_dir)
    treatment_pairs = load_benchmark(args.treatment_dir)

    if not control_pairs:
        print(f"ERROR: no benchmark pairs in {args.control_dir}", file=sys.stderr)
        sys.exit(1)
    if not treatment_pairs:
        print(f"ERROR: no benchmark pairs in {args.treatment_dir}", file=sys.stderr)
        sys.exit(1)

    control_ledgers = None
    treatment_ledgers = None
    if args.enable_calibration_fdr:
        control_ledgers = _load_ledgers_for_dir(args.control_dir)
        treatment_ledgers = _load_ledgers_for_dir(args.treatment_dir)

    digest = compare(
        control_pairs,
        treatment_pairs,
        args.experiment_name,
        control_ledgers=control_ledgers,
        treatment_ledgers=treatment_ledgers,
        enable_calibration_fdr=args.enable_calibration_fdr,
        calibration_fdr_B=args.calibration_fdr_B,
        calibration_fdr_seed=args.calibration_fdr_seed,
    )
    report = render_comparison(digest)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(report, (args.output_dir / "ab_comparison.md"))
    atomic_write_text(json.dumps(digest, indent=2) + "\n", (args.output_dir / "ab_comparison.json"))
    print(f"Comparison written to {args.output_dir}")
    print(f"  Control grade:   {digest['control_grade']}")
    print(f"  Treatment grade: {digest['treatment_grade']}")


if __name__ == "__main__":
    main()
