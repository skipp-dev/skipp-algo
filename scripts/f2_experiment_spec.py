"""F2 contextual-promotion experiment spec loader.

Plan reference: ``smc_improvement_plan_q3_q4_2026-04-20.md`` §2.3 F2 +
§2.4 G3. Decision memo: ``docs/f2_contextual_promotion_decision_2026-
04-21.md``.

The F2 experiment switches the *zone-priority scorer config* between
the in-production global weights (control) and the contextual weights
plus FVG quality score (treatment). It is **not** a symbol-level
enrichment-flag override — that's what
:class:`scripts.smc_ab_experiment.Experiment` is for. Both arms ingest
the same events; only the calibration artifact loaded by the scorer
differs.

This module loads the spec JSON, validates the schema-pinned fields,
and exposes helpers to:

* Resolve the calibration artifact paths for each arm.
* Build the :class:`scripts.smc_sprt_stop_rule.SPRTConfig` from the
  ``sprt`` block.
* Evaluate the rollback gate against a sequence of daily comparison
  records.
* Evaluate the full promotion gate (SPRT + KPI deltas + rollback
  status) against a comparison digest produced by
  :func:`scripts.run_ab_comparison.compare`.

The spec is read-only at runtime; promotion/rejection mutates other
files (calibration JSON, docs/CALIBRATION_DECISIONS.md), never the
spec itself.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scripts.smc_sprt_stop_rule import SPRTConfig

SPEC_SCHEMA_VERSION = 1


GateDecision = Literal["promote", "hold", "rollback", "insufficient_data"]


@dataclass(frozen=True)
class ArmSpec:
    """Single arm of the F2 experiment."""

    label: str
    calibration_artifact: Path
    description: str


@dataclass(frozen=True)
class RollbackGateSpec:
    consecutive_worse_runs: int
    comparison_metric: str

    def __post_init__(self) -> None:
        if self.consecutive_worse_runs < 1:
            raise ValueError(
                f"consecutive_worse_runs must be >= 1, got {self.consecutive_worse_runs}"
            )


@dataclass(frozen=True)
class KpiThresholdSpec:
    """Promote-KPI thresholds for the F2 gate (W8-2).

    stat-review wave 8: these used to be hardcoded literals inside
    :func:`_check_kpi_gate`, duplicating both the spec's prose
    ``promotion_gate.requires`` strings and run_ab_comparison's
    PROMOTE_IMPROVEMENT / HIT_RATE_REGRESSION_TOLERANCE constants. They
    are now read from the spec (``promotion_gate.kpi_thresholds``) so a
    spec change actually propagates to the promote path. Defaults match
    the canonical run_ab_comparison values, so a spec without an explicit
    block keeps the historical behaviour.
    """

    calibrated_brier_max_delta: float = -0.005
    calibrated_ece_max_delta: float = -0.005
    hit_rate_min_delta_pp: float = -1.0


@dataclass(frozen=True)
class F2Spec:
    """Parsed F2 experiment spec (schema_version=1)."""

    name: str
    plan_reference: str
    decision_memo: str
    status: str
    control: ArmSpec
    treatment: ArmSpec
    sprt: SPRTConfig
    rollback_gate: RollbackGateSpec
    promotion_requires: tuple[str, ...]
    on_promote: tuple[str, ...]
    on_reject: tuple[str, ...]
    min_days: int
    min_events_per_arm: int
    promotion_gate_kpi: KpiThresholdSpec

    @property
    def control_artifact(self) -> Path:
        return self.control.calibration_artifact

    @property
    def treatment_artifact(self) -> Path:
        return self.treatment.calibration_artifact


def _require(d: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise ValueError(f"{ctx}: missing required key '{key}'")
    return d[key]


def _arm(d: dict[str, Any], ctx: str) -> ArmSpec:
    return ArmSpec(
        label=str(_require(d, "label", ctx)),
        calibration_artifact=Path(_require(d, "calibration_artifact", ctx)),
        description=str(d.get("description", "")),
    )


def _kpi_thresholds(d: dict[str, Any]) -> KpiThresholdSpec:
    """Parse the optional ``promotion_gate.kpi_thresholds`` block (W8-2).

    Missing keys fall back to the canonical run_ab_comparison defaults so
    a spec without the block is unchanged from the historical hardcoded
    behaviour.
    """
    defaults = KpiThresholdSpec()
    return KpiThresholdSpec(
        calibrated_brier_max_delta=float(
            d.get("calibrated_brier_max_delta", defaults.calibrated_brier_max_delta)
        ),
        calibrated_ece_max_delta=float(
            d.get("calibrated_ece_max_delta", defaults.calibrated_ece_max_delta)
        ),
        hit_rate_min_delta_pp=float(
            d.get("hit_rate_min_delta_pp", defaults.hit_rate_min_delta_pp)
        ),
    )


def load_f2_spec(path: Path) -> F2Spec:
    """Load and validate an F2 spec JSON file.

    Raises :class:`ValueError` on schema mismatch or missing required
    fields. Path normalization is *not* performed — the calibration
    artifact paths are kept exactly as the spec records them so the
    caller can resolve them against the workspace root deterministically.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    schema = raw.get("schema_version")
    if schema != SPEC_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version: got {schema!r}, expected {SPEC_SCHEMA_VERSION}"
        )

    arms = _require(raw, "arms", "spec")
    sprt_raw = _require(raw, "sprt", "spec")
    rb_raw = _require(raw, "rollback_gate", "spec")
    prom_raw = _require(raw, "promotion_gate", "spec")
    win_raw = _require(raw, "data_window", "spec")

    sprt = SPRTConfig(
        p0=float(_require(sprt_raw, "p0", "sprt")),
        p1=float(_require(sprt_raw, "p1", "sprt")),
        alpha=float(sprt_raw.get("alpha", 0.05)),
        beta=float(sprt_raw.get("beta", 0.20)),
        max_n=sprt_raw.get("max_n"),
    )

    return F2Spec(
        name=str(_require(raw, "name", "spec")),
        plan_reference=str(raw.get("plan_reference", "")),
        decision_memo=str(raw.get("decision_memo", "")),
        status=str(raw.get("status", "registered")),
        control=_arm(_require(arms, "control", "arms"), "arms.control"),
        treatment=_arm(_require(arms, "treatment", "arms"), "arms.treatment"),
        sprt=sprt,
        rollback_gate=RollbackGateSpec(
            consecutive_worse_runs=int(
                _require(rb_raw, "consecutive_worse_runs", "rollback_gate")
            ),
            comparison_metric=str(
                _require(rb_raw, "comparison_metric", "rollback_gate")
            ),
        ),
        promotion_requires=tuple(prom_raw.get("requires", [])),
        on_promote=tuple(prom_raw.get("on_promote", [])),
        on_reject=tuple(prom_raw.get("on_reject", [])),
        min_days=int(win_raw.get("min_days", 30)),
        min_events_per_arm=int(win_raw.get("min_events_per_arm", 600)),
        promotion_gate_kpi=_kpi_thresholds(prom_raw.get("kpi_thresholds", {})),
    )


def evaluate_rollback(
    daily_deltas: list[float],
    spec: F2Spec,
) -> bool:
    """Return True iff the rollback gate triggers on *daily_deltas*.

    ``daily_deltas`` is a chronologically-ordered list of
    ``treatment_metric - control_metric`` values for the configured
    comparison metric (lower-is-better, so positive = worse). Triggers
    when the trailing ``consecutive_worse_runs`` entries are *all*
    strictly positive, or — fail-closed (W5-1) — when any trailing
    entry is NaN (a non-measurable delta must never silence the gate).
    """
    n = spec.rollback_gate.consecutive_worse_runs
    if len(daily_deltas) < n:
        return False
    tail = daily_deltas[-n:]
    # W5-1 (stat-review wave 5): NaN > 0 evaluates False, silencing
    # rollback when any tail entry is NaN.  Fail-closed: treat NaN as
    # worse (positive) so the gate does not miss a degradation signal.
    if any(math.isnan(d) for d in tail):
        return True
    return all(d > 0 for d in tail)


def evaluate_promotion(
    digest: dict[str, Any],
    spec: F2Spec,
    *,
    daily_deltas: list[float] | None = None,
) -> dict[str, Any]:
    """Map an A/B comparison digest to a final F2 promote/hold/rollback.

    Reads:
    * ``digest["sprt"]["decision"]`` — produced by
      :func:`scripts.run_ab_comparison._sprt_decision`.
    * ``digest["sprt"]["n"]`` — treatment-arm event count.
    * ``digest["metrics"]`` — Brier/ECE/HR delta rows.

    Returns ``{"decision": GateDecision, "reason": str, "actions": tuple}``.
    Pure read-only; never mutates ``digest`` or ``spec``.
    """
    sprt = digest.get("sprt") or {}
    sprt_decision = sprt.get("decision")
    n = int(sprt.get("n") or 0)

    # Insufficient sample size first — never promote on thin data.
    if n < spec.min_events_per_arm:
        return {
            "decision": "insufficient_data",
            "reason": (
                f"treatment n={n} < min_events_per_arm={spec.min_events_per_arm}; "
                f"continue accumulating"
            ),
            "actions": (),
        }

    # Rollback if SPRT accepts H0 OR rollback gate triggers on deltas.
    rollback_triggered = (
        evaluate_rollback(daily_deltas or [], spec)
        if daily_deltas
        else False
    )
    if sprt_decision == "accept_h0" or rollback_triggered:
        reason_parts = []
        if sprt_decision == "accept_h0":
            reason_parts.append(
                f"SPRT accepted H0 (n={n}, k={sprt.get('k')}, llr={sprt.get('llr')})"
            )
        if rollback_triggered:
            n_runs = spec.rollback_gate.consecutive_worse_runs
            tail = (daily_deltas or [])[-n_runs:]
            if any(math.isnan(d) for d in tail):
                # W5-1 fail-closed path: a NaN tail entry triggers the
                # gate regardless of the other deltas — saying "all
                # worse" here would falsify the audit trail.
                reason_parts.append(
                    f"rollback_gate triggered (fail-closed): non-measurable "
                    f"(NaN) delta in trailing {n_runs} runs on "
                    f"{spec.rollback_gate.comparison_metric}"
                )
            else:
                reason_parts.append(
                    f"rollback_gate triggered: trailing "
                    f"{n_runs} runs all worse on "
                    f"{spec.rollback_gate.comparison_metric}"
                )
        return {
            "decision": "rollback",
            "reason": "; ".join(reason_parts),
            "actions": spec.on_reject,
        }

    # Promote only when SPRT accepts H1 AND KPI gate is satisfied.
    if sprt_decision == "accept_h1":
        kpi = _check_kpi_gate(digest, spec.promotion_gate_kpi)
        if kpi["ok"]:
            return {
                "decision": "promote",
                "reason": (
                    f"SPRT accepted H1 (n={n}, k={sprt.get('k')}, "
                    f"llr={sprt.get('llr')}) and KPI deltas within thresholds: "
                    f"{kpi['summary']}"
                ),
                "actions": spec.on_promote,
            }
        return {
            "decision": "hold",
            "reason": (
                f"SPRT accepted H1 but KPI gate not satisfied: {kpi['summary']}"
            ),
            "actions": (),
        }

    # SPRT inconclusive (continue, max_n_reached, or inconclusive without verdict).
    return {
        "decision": "hold",
        "reason": (
            f"SPRT inconclusive (decision={sprt_decision}, n={n}); "
            f"keep accumulating data"
        ),
        "actions": (),
    }


def _row(rows: list[dict[str, Any]], metric: str) -> dict[str, Any] | None:
    for r in rows:
        if r.get("metric") == metric:
            return r
    return None


def _check_kpi_gate(
    digest: dict[str, Any], thresholds: KpiThresholdSpec
) -> dict[str, Any]:
    """Apply the canonical promote-KPI gate.

    W8-2 (stat-review wave 8): thresholds are read from the F2 spec
    (``promotion_gate.kpi_thresholds`` -> :class:`KpiThresholdSpec`)
    instead of hardcoded literals, so a spec change propagates to the
    promote path. Defaults still mirror :mod:`scripts.run_ab_comparison`:
    PROMOTE_IMPROVEMENT=0.005 for calibrated_brier and calibrated_ece
    (lower-is-better), HIT_RATE_REGRESSION_TOLERANCE=1.0pp.
    """
    rows = digest.get("metrics") or []
    cb = _row(rows, "calibrated_brier") or {}
    ce = _row(rows, "calibrated_ece") or {}
    hr = _row(rows, "hit_rate_pct") or {}

    cb_d = float(cb.get("delta") or 0.0)
    ce_d = float(ce.get("delta") or 0.0)
    hr_d = float(hr.get("delta") or 0.0)

    cb_ok = cb_d <= thresholds.calibrated_brier_max_delta
    ce_ok = ce_d <= thresholds.calibrated_ece_max_delta
    hr_ok = hr_d >= thresholds.hit_rate_min_delta_pp
    ok = cb_ok and ce_ok and hr_ok
    return {
        "ok": ok,
        "summary": (
            f"calibrated_brier_delta={cb_d:+.4f} (ok={cb_ok}), "
            f"calibrated_ece_delta={ce_d:+.4f} (ok={ce_ok}), "
            f"hit_rate_delta={hr_d:+.2f}pp (ok={hr_ok})"
        ),
    }
