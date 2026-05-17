"""Sprint X2 — PromotionGate consolidator.

Aggregates the per-check verdicts (Brier, FDR p-value, PSR/MinTRL, PSI,
live-Brier-vs-walkforward ratio) into a single ``Decision`` per event
family. Pure aggregator: every threshold here mirrors the one already
enforced inside the originating sprint's module. Changing a threshold in
this file alone must NOT shift the gate behaviour — the source of truth
remains the per-sprint module.

Schema is pinned at ``DECISION_SCHEMA_VERSION = 1`` so downstream
consumers (the future C7.1 decision-first dashboard panel, the markdown
audit reports, and the X3 run-manifest header) can rely on a stable
contract.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from governance.types import Blocker, Decision, EventFamily, Posture

DECISION_SCHEMA_VERSION = 1

# Default thresholds mirrored here for aggregation only.
# The source of truth for each threshold is the originating sprint's
# module and/or sprint-plan document that introduced the check; the
# constants below MUST stay aligned with those upstream definitions.
# Updating a value in this file alone must NOT change gate semantics.
#
# Pointers (verified 2026-04-27):
#   * Brier (0.22):       gate-level absolute cap; the live recalibrator
#                         tracks a separate brier_regret_threshold (~0.02)
#                         in the C10 ML layer (see
#                         docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md).
#                         No module-level CALIBRATED_BRIER_TARGET exists
#                         today — this gate is the sole source of truth.
#   * ECE (0.05):         gate is the source of truth
#                         (docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md).
#   * FDR-q (0.05):       scripts/run_ab_comparison.py::FDR_Q.
#   * PSR/MinTRL:         docs/SPRINT_PLAN_C6_PSR_MINTRL_2026-04-26.md and
#                         open_prep/stats_helpers.py::probabilistic_sharpe
#                         / min_trl.
#   * PSI (0.25):         consolidator's hard cap, above the per-feature
#                         drift-alarm thresholds defined for the C9 drift
#                         layer (see docs/SPRINT_PLAN_C9_DRIFT_2026-04-26.md).
#                         The ml/drift/ package does not yet expose a
#                         module-level constant.
#   * live/wf (1.5):      docs/SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md.
DEFAULT_BRIER_MAX = 0.22
DEFAULT_ECE_MAX = 0.05
DEFAULT_FDR_Q = 0.05
DEFAULT_PSR_MIN = 0.95
DEFAULT_MINTRL_MAX_YEARS = 2.0
DEFAULT_PSI_MAX = 0.25
DEFAULT_LIVE_VS_WF_RATIO_MAX = 1.5
# Sprint C9.1: PSI-trend thresholds. Defaults mirror ml.drift.trend.
# Pure slope on the trailing ``psi_trend_window`` samples (per uniform
# time step, typically one observation per day).
DEFAULT_PSI_TREND_WINDOW = 7
DEFAULT_PSI_TREND_SLOPE_WARN = 0.005
DEFAULT_PSI_TREND_SLOPE_ALARM = 0.015


@dataclass(frozen=True)
class GateThresholds:
    brier_max: float = DEFAULT_BRIER_MAX
    ece_max: float = DEFAULT_ECE_MAX
    fdr_q: float = DEFAULT_FDR_Q
    psr_min: float = DEFAULT_PSR_MIN
    mintrl_max_years: float = DEFAULT_MINTRL_MAX_YEARS
    psi_max: float = DEFAULT_PSI_MAX
    live_vs_wf_ratio_max: float = DEFAULT_LIVE_VS_WF_RATIO_MAX
    psi_trend_window: int = DEFAULT_PSI_TREND_WINDOW
    psi_trend_slope_warn: float = DEFAULT_PSI_TREND_SLOPE_WARN
    psi_trend_slope_alarm: float = DEFAULT_PSI_TREND_SLOPE_ALARM


@dataclass
class FamilyMetrics:
    """Per-family snapshot consumed by the consolidator.

    Any field set to ``None`` is treated as "check not yet available":
    the consolidator emits an ``info``-severity blocker AND counts the
    check as failing, so promotion is blocked until the metric is
    actually measured. ``info`` distinguishes "missing" from a real
    threshold breach (which uses ``blocker``) but it does not relax the
    promotion contract — a partially measured family is never promoted.
    """

    family: EventFamily
    brier: float | None = None
    ece: float | None = None
    fdr_pvalue: float | None = None
    psr: float | None = None
    mintrl_years: float | None = None
    psi: float | None = None
    # Sprint C9.1: optional trailing PSI samples (one per uniform time
    # step, typically per day). When at least 2 samples are present the
    # consolidator additionally evaluates a slope-based trend alert.
    psi_history: Sequence[float] = field(default_factory=tuple)
    live_brier: float | None = None
    walkforward_brier: float | None = None
    extras: dict[str, float] = field(default_factory=dict)


def _check(
    *,
    name: str,
    observed: float | None,
    threshold: float,
    lower_is_better: bool,
    blockers: list[Blocker],
    metrics: dict[str, float],
    label: str | None = None,
) -> bool:
    """Run a single threshold check; mutate blockers/metrics; return ok-flag."""
    label = label or name
    if observed is None:
        # ``observed`` is ``None`` (not NaN) so the Decision payload stays
        # safe to serialize with ``json.dumps(..., allow_nan=False)``,
        # which is the policy used by every downstream consumer.
        blockers.append({
            "check": name,
            "severity": "info",
            "observed": None,
            "threshold": threshold,
            "message": f"{label} not yet measured",
        })
        return False
    metrics[label] = float(observed)
    ok = (observed <= threshold) if lower_is_better else (observed >= threshold)
    if not ok:
        direction = "<=" if lower_is_better else ">="
        blockers.append({
            "check": name,
            "severity": "blocker",
            "observed": float(observed),
            "threshold": float(threshold),
            "message": f"{label}={observed:.4f} fails {direction} {threshold:.4f}",
        })
    return ok


def _posture(blockers: Iterable[Blocker]) -> Posture:
    """Map blocker severities to a four-step traffic light.

    Any ``info`` severity (missing metric) blocks promotion in
    ``evaluate``, so posture must downgrade to at least ``yellow`` to
    avoid the contradictory ``posture='green'`` + ``promoted=False``
    output that an ``info`` blocker would otherwise produce.
    """
    sev = [b["severity"] for b in blockers]
    n_blocker = sev.count("blocker")
    n_warning = sev.count("warning")
    n_info = sev.count("info")
    if n_blocker >= 2:
        return "red"
    if n_blocker == 1:
        return "orange"
    if n_warning >= 1 or n_info >= 1:
        return "yellow"
    return "green"


class PromotionGate:
    """Consolidator over per-sprint gate checks.

    Usage::

        gate = PromotionGate()
        decision = gate.evaluate(FamilyMetrics(
            family="BOS", brier=0.18, ece=0.03, fdr_pvalue=0.01,
            psr=0.97, mintrl_years=1.4, psi=0.12,
            live_brier=0.20, walkforward_brier=0.18,
        ))
        if decision["promoted"]:
            ...
    """

    def __init__(self, thresholds: GateThresholds | None = None) -> None:
        self.thresholds = thresholds or GateThresholds()

    def evaluate(self, snapshot: FamilyMetrics) -> Decision:
        t = self.thresholds
        blockers: list[Blocker] = []
        metrics: dict[str, float] = {}

        ok_brier = _check(
            name="brier_threshold",
            observed=snapshot.brier,
            threshold=t.brier_max,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="brier",
        )
        ok_ece = _check(
            name="ece_threshold",
            observed=snapshot.ece,
            threshold=t.ece_max,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="ece",
        )
        ok_fdr = _check(
            name="fdr_significance",
            observed=snapshot.fdr_pvalue,
            threshold=t.fdr_q,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="fdr_pvalue",
        )
        ok_psr = _check(
            name="psr_minimum",
            observed=snapshot.psr,
            threshold=t.psr_min,
            lower_is_better=False,
            blockers=blockers,
            metrics=metrics,
            label="psr",
        )
        ok_mintrl = _check(
            name="mintrl_horizon",
            observed=snapshot.mintrl_years,
            threshold=t.mintrl_max_years,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="mintrl_years",
        )
        ok_psi = _check(
            name="psi_drift",
            observed=snapshot.psi,
            threshold=t.psi_max,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="psi",
        )

        # Sprint C9.1: PSI-trend alert on top of the level check. A
        # slow-creeping climb (0.05 -> 0.20 over 14 days) stays below
        # ``psi_max`` the entire time but should still degrade posture
        # and, at ``trend_alarm``, block promotion. We only run the
        # trend check when the caller supplied >= 2 samples so default
        # callers (no history) keep their previous behaviour.
        if snapshot.psi_history and len(snapshot.psi_history) >= 2:
            from ml.drift.trend import psi_trend_alert
            trend = psi_trend_alert(
                snapshot.psi_history,
                window=t.psi_trend_window,
                slope_warn=t.psi_trend_slope_warn,
                slope_alarm=t.psi_trend_slope_alarm,
            )
            metrics["psi_slope_per_day"] = float(trend.slope_per_day)
            if trend.severity == "trend_alarm":
                blockers.append({
                    "check": "psi_trend",
                    "severity": "blocker",
                    "observed": float(trend.slope_per_day),
                    "threshold": float(t.psi_trend_slope_alarm),
                    "message": (
                        f"psi slope {trend.slope_per_day:+.4f}/step exceeds "
                        f"alarm {t.psi_trend_slope_alarm:+.4f}"
                    ),
                })
                ok_psi = False
            elif trend.severity == "trend_warn":
                blockers.append({
                    "check": "psi_trend",
                    "severity": "warning",
                    "observed": float(trend.slope_per_day),
                    "threshold": float(t.psi_trend_slope_warn),
                    "message": (
                        f"psi slope {trend.slope_per_day:+.4f}/step exceeds "
                        f"warn {t.psi_trend_slope_warn:+.4f}"
                    ),
                })

        # Live-vs-WF ratio: needs both sides to exist; computed here since
        # neither sprint owns it standalone. The math is delegated to
        # ``scripts.forward_test_tracking.expected_vs_realized_ratio`` so
        # both PromotionGate and the C8.1 forward-test tracker share a
        # single edge-case-safe implementation (wf<=0 / non-finite => None).
        from scripts.forward_test_tracking import expected_vs_realized_ratio
        if snapshot.live_brier is not None and snapshot.walkforward_brier is not None:
            ratio = expected_vs_realized_ratio(
                snapshot.live_brier, snapshot.walkforward_brier
            )
            if ratio is None:
                blockers.append({
                    "check": "live_vs_wf_ratio",
                    "severity": "info",
                    "observed": None,
                    "threshold": float(t.live_vs_wf_ratio_max),
                    "message": (
                        "live_vs_wf_ratio undefined "
                        "(walkforward_brier <= 0 or non-finite input)"
                    ),
                })
                ok_live = False
            else:
                metrics["live_vs_wf_ratio"] = float(ratio)
                if ratio > t.live_vs_wf_ratio_max:
                    blockers.append({
                        "check": "live_vs_wf_ratio",
                        "severity": "blocker",
                        "observed": float(ratio),
                        "threshold": float(t.live_vs_wf_ratio_max),
                        "message": (
                            f"live/wf brier ratio={ratio:.2f} exceeds "
                            f"{t.live_vs_wf_ratio_max:.2f}"
                        ),
                    })
                    ok_live = False
                else:
                    ok_live = True
        else:
            blockers.append({
                "check": "live_vs_wf_ratio",
                "severity": "info",
                "observed": None,
                "threshold": float(t.live_vs_wf_ratio_max),
                "message": "live or walkforward brier not yet measured",
            })
            ok_live = False

        for k, v in snapshot.extras.items():
            metrics[f"extra.{k}"] = float(v)

        promoted = all((ok_brier, ok_ece, ok_fdr, ok_psr, ok_mintrl, ok_psi, ok_live))
        decision: Decision = {
            "schema_version": DECISION_SCHEMA_VERSION,
            "family": snapshot.family,
            "promoted": promoted,
            "posture": _posture(blockers),
            "blockers": blockers,
            "metrics": metrics,
        }
        return decision

    def audit(self, decision: Decision) -> str:
        """Human-readable single-string summary for dashboards / logs."""
        head = (
            f"[{decision['posture'].upper()}] {decision['family']} "
            f"{'PROMOTED' if decision['promoted'] else 'BLOCKED'}"
        )
        if not decision["blockers"]:
            return head
        lines = [head]
        for b in decision["blockers"]:
            lines.append(f"  - {b['severity']}/{b['check']}: {b['message']}")
        return "\n".join(lines)


__all__ = [
    "DECISION_SCHEMA_VERSION",
    "FamilyMetrics",
    "GateThresholds",
    "PromotionGate",
]
