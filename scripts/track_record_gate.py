"""Track-Record-Gate aggregator (Sprint C6 / T6 — closes C2/T7, C3/T6, C4/T6, C5/T7, C6/T5+T6).

Combines the statistical inference deliverables produced by C2-C6
(walk-forward, bootstrap-CI, permutation-p, regime concentration, PSR /
MinTRL) into a single deterministic verdict object that downstream code
(public report, dashboard, drift watchdog) can render unchanged.

The mindestanforderungen are taken verbatim from
``docs/SPRINT_ROADMAP_C2_C9_CONSOLIDATED_2026-04-26.md``.

Inputs are intentionally minimal — a list of per-trade ``returns`` plus
optional aggregate scalars that callers may have computed elsewhere
(walk-forward-efficiency, permutation-p, regime concentration). Any
metric whose inputs are missing simply yields ``status="skipped"`` and
does not block the verdict — the verdict only flips ``red`` on a
*failed* (computed but below threshold) check.

The module is pure-stdlib + numpy, mirrors the boundary discipline of
the existing inference scripts, and is safe to import from the public
report builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from open_prep.stats_helpers import min_trl, probabilistic_sharpe
from scripts.performance_inference import (
    max_dd_ci,
    profit_factor_ci,
    sharpe_ci,
    win_rate_ci,
)

# ---------------------------------------------------------------------------
# Thresholds (single source of truth; mirrors the consolidated roadmap)
# ---------------------------------------------------------------------------

MIN_OOS_TRADES = 100
MIN_WIN_RATE_R1 = 0.55
MIN_WIN_RATE_RGE15 = 0.45
MIN_SHARPE_ANNUALIZED = 1.0
MIN_BOOTSTRAP_SHARPE_CI_LOW = 0.3
MAX_DRAWDOWN_PCT = 0.15
MAX_FDR_RATE = 0.10
MIN_WALK_FORWARD_EFFICIENCY = 0.50
MAX_PERMUTATION_P = 0.05
MAX_PER_REGIME_HIT_RATE_SPREAD = 0.20
MIN_PSR = 0.95

# Canonical roster of gate-check names emitted by
# :func:`evaluate_track_record_gate`. Pinned here so dashboard /
# methodology-drawer consumers can validate their failure-string handling
# against a single source of truth (C-sprint deep-review MAJOR finding:
# unknown failure codes were silently coerced to opaque strings on the
# Streamlit dashboard). Adding a new check requires updating this
# constant **and** the consumer roundtrip test in
# ``tests/test_track_record_gate.py::test_evaluate_emits_all_known_check_names``.
KNOWN_GATE_CHECK_NAMES: tuple[str, ...] = (
    "oos_trades",
    "win_rate",
    "sharpe",
    "bootstrap_sharpe_ci_low",
    "max_drawdown",
    "walk_forward_efficiency",
    "permutation_p",
    "fdr_rate",
    "per_regime_hit_rate_spread",
    "psr_sr_star_zero",
    "min_trl_within_n",
)

GREEN = "green"
YELLOW = "yellow"
RED = "red"
SKIPPED = "skipped"


@dataclass(frozen=True)
class GateCheck:
    """Single-criterion verdict — additive, never raises."""

    name: str
    status: str  # "green" | "yellow" | "red" | "skipped"
    value: float | None = None
    threshold: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class TrackRecordGateVerdict:
    """Aggregate verdict — stable schema for dashboard + public report."""

    status: str  # "green" | "yellow" | "red"
    checks: list[GateCheck] = field(default_factory=list)
    n_trades: int = 0
    summary: dict[str, Any] = field(default_factory=dict)


def _check(
    name: str,
    *,
    value: float | None,
    threshold: float,
    direction: str,
    detail: str = "",
) -> GateCheck:
    """``direction``: ``"ge"`` (value must be >= threshold) or ``"le"``."""

    if value is None or not np.isfinite(value):
        return GateCheck(name=name, status=SKIPPED, threshold=threshold, detail=detail or "missing")
    passed = value >= threshold if direction == "ge" else value <= threshold
    return GateCheck(
        name=name,
        status=GREEN if passed else RED,
        value=float(value),
        threshold=float(threshold),
        detail=detail,
    )


def _aggregate_status(checks: Sequence[GateCheck]) -> str:
    """Worst-of-finite — RED dominates, then YELLOW, then GREEN. SKIPPED ignored."""

    if any(c.status == RED for c in checks):
        return RED
    if any(c.status == YELLOW for c in checks):
        return YELLOW
    return GREEN


def evaluate_track_record_gate(
    returns: Sequence[float],
    *,
    rr_target: float = 1.0,
    walk_forward_efficiency: float | None = None,
    permutation_p: float | None = None,
    fdr_rate: float | None = None,
    per_regime_hit_rate_spread: float | None = None,
    sharpe_freq: int = 252,
    bootstrap_B: int = 500,
    bootstrap_seed: int = 42,
) -> TrackRecordGateVerdict:
    """Compute the consolidated Track-Record-Gate verdict.

    Args:
        returns: per-trade returns (R-multiples or fractional). Treated
            as the OOS sample.
        rr_target: target reward/risk used to choose the Win-Rate
            threshold (1.0 → 0.55, ≥1.5 → 0.45).
        walk_forward_efficiency: pre-computed WFE (C2/T4 output). When
            ``None`` the WFE check is skipped.
        permutation_p: pre-computed permutation p-value (C4 output).
            When ``None`` the permutation check is skipped.
        fdr_rate: pre-computed FDR rate (C3/T4 + C4/T4 BH output). When
            ``None`` the FDR check is skipped.
        per_regime_hit_rate_spread: max-min hit-rate spread across
            regimes (C5/T3 output). When ``None`` the regime check is
            skipped.
        sharpe_freq: annualisation factor for Sharpe + bootstrap-CI.
        bootstrap_B: bootstrap iterations for the inference helpers.
        bootstrap_seed: deterministic seed for the bootstrap path.

    Returns:
        ``TrackRecordGateVerdict`` with per-criterion checks and an
        aggregate ``green/yellow/red`` status.
    """

    arr = np.asarray(returns, dtype=np.float64).ravel()
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)

    checks: list[GateCheck] = []

    # n
    checks.append(
        _check(
            "oos_trades",
            value=float(n),
            threshold=float(MIN_OOS_TRADES),
            direction="ge",
            detail="≥100, ideal ≥200",
        )
    )

    # Win rate (depends on rr_target). win_rate_ci needs 0/1 outcomes.
    wr_threshold = MIN_WIN_RATE_R1 if rr_target < 1.5 else MIN_WIN_RATE_RGE15
    wins = (arr > 0.0).astype(np.float64)
    wr = win_rate_ci(wins, alpha=0.05, B=bootstrap_B, seed=bootstrap_seed)
    if "skipped_reason" in wr:
        checks.append(GateCheck(name="win_rate", status=SKIPPED, threshold=wr_threshold))
    else:
        checks.append(
            _check(
                "win_rate",
                value=wr.get("value"),
                threshold=wr_threshold,
                direction="ge",
                detail=f"rr_target={rr_target}",
            )
        )

    # Sharpe annualised + bootstrap CI low
    sr = sharpe_ci(
        arr,
        alpha=0.05,
        freq=sharpe_freq,
        B=bootstrap_B,
        method="studentized",
        seed=bootstrap_seed,
    )
    if "skipped_reason" in sr:
        checks.append(GateCheck(name="sharpe", status=SKIPPED, threshold=MIN_SHARPE_ANNUALIZED))
        checks.append(
            GateCheck(name="bootstrap_sharpe_ci_low", status=SKIPPED, threshold=MIN_BOOTSTRAP_SHARPE_CI_LOW)
        )
    else:
        checks.append(
            _check(
                "sharpe",
                value=sr.get("value"),
                threshold=MIN_SHARPE_ANNUALIZED,
                direction="ge",
                detail=f"freq={sharpe_freq}",
            )
        )
        checks.append(
            _check(
                "bootstrap_sharpe_ci_low",
                value=sr.get("ci_low"),
                threshold=MIN_BOOTSTRAP_SHARPE_CI_LOW,
                direction="ge",
                detail=f"method={sr.get('ci_method')}",
            )
        )

    # Max drawdown (lower-better → invert: -dd >= -threshold ↔ dd <= threshold)
    dd = max_dd_ci(arr, alpha=0.05, B=bootstrap_B, seed=bootstrap_seed)
    if "skipped_reason" in dd:
        checks.append(GateCheck(name="max_drawdown", status=SKIPPED, threshold=MAX_DRAWDOWN_PCT))
    else:
        checks.append(
            _check(
                "max_drawdown",
                value=dd.get("value"),
                threshold=MAX_DRAWDOWN_PCT,
                direction="le",
                detail="fractional",
            )
        )

    # Profit factor (informational — not gated, but surfaced)
    pf = profit_factor_ci(arr, alpha=0.05, B=bootstrap_B, seed=bootstrap_seed)

    # WFE
    checks.append(
        _check(
            "walk_forward_efficiency",
            value=walk_forward_efficiency,
            threshold=MIN_WALK_FORWARD_EFFICIENCY,
            direction="ge",
        )
    )

    # Permutation p
    checks.append(
        _check(
            "permutation_p",
            value=permutation_p,
            threshold=MAX_PERMUTATION_P,
            direction="le",
        )
    )

    # FDR
    checks.append(
        _check(
            "fdr_rate",
            value=fdr_rate,
            threshold=MAX_FDR_RATE,
            direction="le",
        )
    )

    # Regime concentration
    checks.append(
        _check(
            "per_regime_hit_rate_spread",
            value=per_regime_hit_rate_spread,
            threshold=MAX_PER_REGIME_HIT_RATE_SPREAD,
            direction="le",
        )
    )

    # PSR / MinTRL
    psr_value: float | None = None
    min_trl_value: float | None = None
    min_trl_no_edge = False
    if n >= 30:
        psr_dict = probabilistic_sharpe(arr.tolist(), sr_star=0.0, annualize=False)
        psr_value = psr_dict["psr"]
        # ``min_trl`` raises ValueError on two distinct conditions:
        # (a) ``sr_hat <= sr_star`` — no detectable edge,
        # (b) ``denom_inner <= 0`` — non-Gaussian variance-term
        #     collapse driven by extreme skew/kurtosis.
        # Both are RED outcomes for the gate, but the detail string
        # must reflect the actual cause so reviewers don't chase the
        # wrong remediation. Previously this branch swallowed both as
        # SKIPPED, which let red gates pass silently (C-sprint deep-
        # review MAJOR fix).
        min_trl_failure_detail: str | None = None
        try:
            min_trl_value = float(
                min_trl(
                    sr_hat=psr_dict["sharpe_hat"],
                    sr_star=0.0,
                    skew=psr_dict["skew"],
                    kurtosis=psr_dict["kurtosis"],
                    alpha=0.05,
                )
            )
        except ValueError as exc:
            min_trl_value = None
            min_trl_no_edge = True
            msg = str(exc).lower()
            if "variance term" in msg:
                min_trl_failure_detail = (
                    "non-Gaussian variance term collapsed "
                    "(extreme skew/kurtosis)"
                )
            else:
                min_trl_failure_detail = "sr_hat <= sr_star (no detectable edge)"
    checks.append(
        _check(
            "psr_sr_star_zero",
            value=psr_value,
            threshold=MIN_PSR,
            direction="ge",
        )
    )
    if min_trl_value is None:
        if min_trl_no_edge:
            checks.append(
                GateCheck(
                    name="min_trl_within_n",
                    status=RED,
                    value=None,
                    threshold=float(n),
                    detail=min_trl_failure_detail
                    or "sr_hat <= sr_star (no detectable edge)",
                )
            )
        else:
            checks.append(
                GateCheck(
                    name="min_trl_within_n",
                    status=SKIPPED,
                    threshold=float(n),
                )
            )
    else:
        ok_trl = min_trl_value <= float(n)
        checks.append(
            GateCheck(
                name="min_trl_within_n",
                status=GREEN if ok_trl else RED,
                value=float(min_trl_value),
                threshold=float(n),
                detail="MinTRL ≤ available n",
            )
        )

    summary: dict[str, Any] = {
        "win_rate": wr,
        "win_rate_threshold": wr_threshold,
        "rr_target": float(rr_target),
        "sharpe": sr,
        "max_drawdown": dd,
        "profit_factor": pf,
        "psr": psr_value,
        "min_trl": min_trl_value,
        "walk_forward_efficiency": walk_forward_efficiency,
        "permutation_p": permutation_p,
        "fdr_rate": fdr_rate,
        "per_regime_hit_rate_spread": per_regime_hit_rate_spread,
    }

    return TrackRecordGateVerdict(
        status=_aggregate_status(checks),
        checks=list(checks),
        n_trades=n,
        summary=summary,
    )


def verdict_to_dict(verdict: TrackRecordGateVerdict) -> dict[str, Any]:
    """Stable JSON-serialisable form for dashboard / public report."""

    return {
        "status": verdict.status,
        "n_trades": int(verdict.n_trades),
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "value": c.value,
                "threshold": c.threshold,
                "detail": c.detail,
            }
            for c in verdict.checks
        ],
        "summary": verdict.summary,
    }


def evaluate_track_record_gate_per_variant(
    returns_by_variant: dict[str, Sequence[float]],
    *,
    walk_forward_efficiency_by_variant: dict[str, float] | None = None,
    permutation_p_by_variant: dict[str, float] | None = None,
    fdr_rate_by_variant: dict[str, float] | None = None,
    per_regime_hit_rate_spread_by_variant: dict[str, float] | None = None,
    rr_target: float = 1.0,
    sharpe_freq: int = 252,
    bootstrap_B: int = 500,
    bootstrap_seed: int = 42,
) -> dict[str, dict[str, Any]]:
    """Compute one verdict per variant — closes the C7 per-row gating gap.

    Returns ``{variant: verdict_dict}`` where each value is the dict
    form produced by :func:`verdict_to_dict` plus a ``failures`` list
    of human-readable reasons for ``red`` checks. The companion
    ``per_variant`` block is consumed by ``build_dashboard_payload``
    via :func:`scripts.build_dashboard_payload._per_variant_gate_status`.

    The optional per-variant scalar dicts (WFE, permutation-p, FDR,
    regime spread) mirror the kwargs of :func:`evaluate_track_record_gate`;
    a missing key skips that check for that variant rather than failing it.
    """

    wfe = walk_forward_efficiency_by_variant or {}
    perm = permutation_p_by_variant or {}
    fdr = fdr_rate_by_variant or {}
    spread = per_regime_hit_rate_spread_by_variant or {}

    out: dict[str, dict[str, Any]] = {}
    for variant, returns in returns_by_variant.items():
        verdict = evaluate_track_record_gate(
            returns,
            rr_target=rr_target,
            walk_forward_efficiency=wfe.get(variant),
            permutation_p=perm.get(variant),
            fdr_rate=fdr.get(variant),
            per_regime_hit_rate_spread=spread.get(variant),
            sharpe_freq=sharpe_freq,
            bootstrap_B=bootstrap_B,
            bootstrap_seed=bootstrap_seed,
        )
        as_dict = verdict_to_dict(verdict)
        as_dict["failures"] = [
            (
                f"{c.name}={c.value:.4f} vs threshold {c.threshold:.4f}"
                if c.value is not None and c.threshold is not None
                else c.name
            )
            for c in verdict.checks
            if c.status == RED
        ]
        out[variant] = as_dict
    return out
