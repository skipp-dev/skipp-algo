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
    strictly positive.
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
            reason_parts.append(
                f"rollback_gate triggered: trailing "
                f"{spec.rollback_gate.consecutive_worse_runs} runs all worse on "
                f"{spec.rollback_gate.comparison_metric}"
            )
        return {
            "decision": "rollback",
            "reason": "; ".join(reason_parts),
            "actions": spec.on_reject,
        }

    # Promote only when SPRT accepts H1 AND KPI gate is satisfied.
    if sprt_decision == "accept_h1":
        kpi = _check_kpi_gate(digest)
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


def _check_kpi_gate(digest: dict[str, Any]) -> dict[str, Any]:
    """Apply the canonical promote-KPI gate from run_ab_comparison.

    Mirrors the thresholds in :mod:`scripts.run_ab_comparison`:
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

    cb_ok = cb_d <= -0.005
    ce_ok = ce_d <= -0.005
    hr_ok = hr_d >= -1.0
    ok = cb_ok and ce_ok and hr_ok
    return {
        "ok": ok,
        "summary": (
            f"calibrated_brier_delta={cb_d:+.4f} (ok={cb_ok}), "
            f"calibrated_ece_delta={ce_d:+.4f} (ok={ce_ok}), "
            f"hit_rate_delta={hr_d:+.2f}pp (ok={hr_ok})"
        ),
    }
