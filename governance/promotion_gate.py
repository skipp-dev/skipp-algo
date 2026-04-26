"""Sprint X2 — PromotionGate consolidator.

Aggregates the per-check verdicts (Brier, FDR p-value, PSR/MinTRL, PSI,
live-Brier-vs-walkforward ratio) into a single ``Decision`` per event
family. Pure aggregator: every threshold here mirrors the one already
enforced inside the originating sprint's module. Changing a threshold in
this file alone must NOT shift the gate behaviour — the source of truth
remains the per-sprint module.

Schema is pinned at ``DECISION_SCHEMA_VERSION = 1`` so downstream
consumers (``streamlit_terminal/decision_first_panel.py`` in C7.1, the
markdown audit reports, the X3 run-manifest header) can rely on a stable
contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from governance.types import Blocker, Decision, EventFamily, Posture

DECISION_SCHEMA_VERSION = 1

# Default thresholds — sourced from:
#   * Brier:        ml/calibration/__init__.py::CALIBRATED_BRIER_TARGET
#   * ECE:          ml/calibration/__init__.py::ECE_TARGET
#   * FDR-q:        scripts/run_ab_comparison.py::FDR_Q
#   * PSR/MinTRL:   docs/SPRINT_PLAN_C6_PSR_MINTRL_2026-04-26.md
#   * PSI level:    ml/drift/__init__.py::PSI_LEVEL_THRESHOLD
#   * live/wf:      docs/SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md
# Overriding any of these here without first updating the source module
# is a contract violation.
DEFAULT_BRIER_MAX = 0.22
DEFAULT_ECE_MAX = 0.05
DEFAULT_FDR_Q = 0.05
DEFAULT_PSR_MIN = 0.95
DEFAULT_MINTRL_MAX_YEARS = 2.0
DEFAULT_PSI_MAX = 0.25
DEFAULT_LIVE_VS_WF_RATIO_MAX = 1.5


@dataclass(frozen=True)
class GateThresholds:
    brier_max: float = DEFAULT_BRIER_MAX
    ece_max: float = DEFAULT_ECE_MAX
    fdr_q: float = DEFAULT_FDR_Q
    psr_min: float = DEFAULT_PSR_MIN
    mintrl_max_years: float = DEFAULT_MINTRL_MAX_YEARS
    psi_max: float = DEFAULT_PSI_MAX
    live_vs_wf_ratio_max: float = DEFAULT_LIVE_VS_WF_RATIO_MAX


@dataclass
class FamilyMetrics:
    """Per-family snapshot consumed by the consolidator.

    Any field set to ``None`` is treated as "check not yet available"
    and emits an ``info``-severity blocker (not a failing one).
    """

    family: EventFamily
    brier: float | None = None
    ece: float | None = None
    fdr_pvalue: float | None = None
    psr: float | None = None
    mintrl_years: float | None = None
    psi: float | None = None
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
        blockers.append({
            "check": name,
            "severity": "info",
            "observed": float("nan"),
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
    """Map blocker severities to a four-step traffic light."""
    sev = [b["severity"] for b in blockers]
    n_blocker = sev.count("blocker")
    n_warning = sev.count("warning")
    n_info = sev.count("info")
    if n_blocker >= 2:
        return "red"
    if n_blocker == 1:
        return "orange"
    if n_warning >= 1 or n_info >= 3:
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

        # Live-vs-WF ratio: needs both sides to exist; computed here since
        # neither sprint owns it standalone.
        if snapshot.live_brier is not None and snapshot.walkforward_brier is not None:
            wf = max(snapshot.walkforward_brier, 1e-9)
            ratio = snapshot.live_brier / wf
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
                "observed": float("nan"),
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
