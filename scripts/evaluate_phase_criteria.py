"""Stat-review F1/F6 (2026-06-10) — machine evaluator for ``PhasePassCriteria``.

The 2026-06 promotion-chain statistical-validity review found that the
``PhasePassCriteria`` dataclasses in :mod:`scripts.run_smc_live_incubation`
were evaluated by **no code anywhere** (F1) and that every ``extra``
criterion string was a prose mirror no code checked (F6).  This module
closes both holes:

* :func:`evaluate_phase_criteria` evaluates every numeric field AND every
  ``extra`` string of a :class:`PhasePassCriteria` against the actual
  artefacts (drift JSON, incubation audit JSONL, watchdog report) and
  returns a structured :class:`PhaseEvalReport`.
* ``_EXTRA_CHECKERS`` is the criterion-string → checker-function registry.
  ``tests/test_evaluate_phase_criteria.py`` asserts every ``extra`` string
  used by any ``PHASE_*_CRITERIA`` has a registered checker — an unmapped
  string is a test failure, so the silent-gate-hole class cannot recur.

Decision semantics (fail-closed)
--------------------------------

Each criterion resolves to one of three states:

* ``passed=True``   — machine-verified against the artefacts.
* ``passed=False``  — machine-verified violation.
* ``passed=None``   — **not machine-evaluable** (missing artefact, or the
  criterion is human-owned like the Phase-C Scale-Phase marker).

``all_passed`` is ``True`` only when every criterion is ``passed=True``.
``None`` counts as **not passed** — a missing artefact must never look
like a satisfied criterion.  Phase-C (``live_full``) therefore can never
machine-pass: its ``scale_phase_backlog_owns_kelly_sizing`` marker always
resolves to ``passed=None`` (human sign-off owns it by design).

Promotion remains **manual sign-off only** per the C8 runbook; this
evaluator turns the checklist from prose into machine-verified *input* to
that sign-off.  ``scripts/run_smc_live_incubation.py`` refuses
``live_small`` / ``live_full`` without a fresh passing report.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from scripts.backfill_live_outcomes import _CLOSED_ACTIONS
from scripts.run_smc_live_incubation import (
    PHASE_PASS_CRITERIA,
    PhasePassCriteria,
)
from scripts.smc_atomic_write import atomic_write_text

logger = logging.getLogger("scripts.evaluate_phase_criteria")

PHASE_EVAL_SCHEMA_VERSION = "1.0.0"

# Which phase's criteria must be PASSED to *enter* a given phase.
# live_small requires the paper (Phase-A) checklist; live_full requires
# the live_small (Phase-B) checklist. paper has no entry gate.
PRIOR_PHASE_FOR_ENTRY: Mapping[str, str] = {
    "live_small": "paper",
    "live_full": "live_small",
}

__all__ = [
    "PHASE_EVAL_SCHEMA_VERSION",
    "PRIOR_PHASE_FOR_ENTRY",
    "CriterionResult",
    "PhaseEvalReport",
    "evaluate_phase_criteria",
    "load_and_validate_eval_report",
    "main",
]


@dataclass(frozen=True)
class CriterionResult:
    """Outcome of evaluating a single promotion criterion."""

    criterion: str
    passed: bool | None
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PhaseEvalReport:
    """Full evaluation of one variant against one phase's criteria."""

    phase: str
    variant: str
    all_passed: bool
    results: tuple[CriterionResult, ...]
    computed_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": PHASE_EVAL_SCHEMA_VERSION,
            "phase": self.phase,
            "variant": self.variant,
            "all_passed": self.all_passed,
            "computed_at": self.computed_at,
            "results": [r.to_json() for r in self.results],
            # Mirror of the runbook contract: a passing report is INPUT
            # to the human sign-off, never a promotion by itself.
            "phase_promotion": "manual_signoff_only",
        }


@dataclass(frozen=True)
class _EvalContext:
    """Everything a checker may consult. All artefacts optional →
    checkers resolve to ``passed=None`` when their input is absent."""

    variant: str
    phase: str
    variant_row: Mapping[str, Any] | None
    audit_records: Sequence[Mapping[str, Any]]
    watchdog_report: Mapping[str, Any] | None


# ── extra-criterion checkers (F6) ──────────────────────────────────


def _check_slippage_ks_pvalue_gt_0_05(ctx: _EvalContext) -> CriterionResult:
    name = "slippage_ks_pvalue_gt_0.05"
    if ctx.variant_row is None:
        return CriterionResult(name, None, "variant absent from drift artifact")
    # Stat-review S5 (#2674): when the KS reference is the synthetic
    # Normal(_DEFAULT_EXPECTED_SLIPPAGE_MEAN, _DEFAULT_EXPECTED_SLIPPAGE_STD)
    # placeholder (no ADR / no calibration provenance), a p-value
    # comparison against it is not a machine-evaluable promotion
    # criterion — refuse rather than compare against folklore.
    ref_type = ctx.variant_row.get("slippage_ks_reference_type")
    if ref_type == "synthetic_normal":
        return CriterionResult(
            name,
            None,
            "slippage_ks_reference_type='synthetic_normal' (uncalibrated "
            "placeholder reference — p-value not machine-evaluable; "
            "supply backtest_samples)",
        )
    p = ctx.variant_row.get("slippage_ks_p")
    if not isinstance(p, (int, float)):
        return CriterionResult(name, None, "slippage_ks_p missing/non-numeric")
    return CriterionResult(
        name, bool(p > 0.05), f"slippage_ks_p={float(p):.6f}"
    )


def _check_hit_rate_inside_c3_bootstrap_ci(ctx: _EvalContext) -> CriterionResult:
    name = "hit_rate_inside_c3_bootstrap_ci"
    if ctx.variant_row is None:
        return CriterionResult(name, None, "variant absent from drift artifact")
    flag = ctx.variant_row.get("hr_in_bootstrap_ci")
    if not isinstance(flag, bool):
        return CriterionResult(
            name, None, "hr_in_bootstrap_ci missing (no CI in backtest reference?)"
        )
    return CriterionResult(name, flag, f"hr_in_bootstrap_ci={flag}")


def _check_kill_switch_never_fired(ctx: _EvalContext) -> CriterionResult:
    name = "kill_switch_never_fired"
    fired = [
        r
        for r in ctx.audit_records
        if r.get("kill_switch_triggered") is True
        and r.get("phase") == ctx.phase
    ]
    if not ctx.audit_records:
        return CriterionResult(name, None, "no audit records supplied")
    return CriterionResult(
        name,
        not fired,
        f"{len(fired)} kill-switch audit record(s) in phase={ctx.phase!r}",
    )


def _check_max_dd_live_lt_2x_backtest(ctx: _EvalContext) -> CriterionResult:
    name = "max_dd_live_lt_2x_backtest"
    if ctx.variant_row is None:
        return CriterionResult(name, None, "variant absent from drift artifact")
    live_dd = ctx.variant_row.get("live_max_dd")
    bt_dd = ctx.variant_row.get("backtest_max_dd")
    if not isinstance(live_dd, (int, float)) or not isinstance(bt_dd, (int, float)):
        return CriterionResult(name, None, "live_max_dd/backtest_max_dd missing")
    if bt_dd <= 0:
        # A zero backtest drawdown makes the 2x bound vacuous/degenerate —
        # refuse rather than auto-pass (degenerate-input laundering class).
        return CriterionResult(
            name, None, f"backtest_max_dd={bt_dd} is non-positive (degenerate bound)"
        )
    return CriterionResult(
        name,
        bool(live_dd < 2.0 * bt_dd),
        f"live_max_dd={live_dd:.6f} vs 2x backtest_max_dd={2.0 * bt_dd:.6f}",
    )


def _check_slippage_ks_reference_backtest_samples(
    ctx: _EvalContext,
) -> CriterionResult:
    name = "slippage_ks_reference_backtest_samples"
    if ctx.variant_row is None:
        return CriterionResult(name, None, "variant absent from drift artifact")
    ref_type = ctx.variant_row.get("slippage_ks_reference_type")
    return CriterionResult(
        name,
        ref_type == "backtest_samples",
        f"slippage_ks_reference_type={ref_type!r}",
    )


def _check_drift_window_complete(ctx: _EvalContext) -> CriterionResult:
    name = "drift_window_complete"
    if ctx.watchdog_report is None:
        return CriterionResult(name, None, "no watchdog report supplied")
    complete = ctx.watchdog_report.get("window_complete")
    if not isinstance(complete, bool):
        return CriterionResult(name, None, "window_complete missing from report")
    return CriterionResult(name, complete, f"window_complete={complete}")


def _check_watchdog_status_not_red(ctx: _EvalContext) -> CriterionResult:
    # Stat-review S1 (#2674): reconcile the two drift stacks. The
    # watchdog's 4-detector consensus (KS-p, PSI, mean-shift, var-ratio
    # → green/yellow/red) can stand RED while the Sharpe-ratio
    # drift_score still reads "pass" (stable mean, blown-out tails).
    # Promotion must consume the watchdog severity, fail-closed.
    name = "watchdog_status_not_red"
    if ctx.watchdog_report is None:
        return CriterionResult(name, None, "no watchdog report supplied")
    severity = ctx.watchdog_report.get("aggregate_severity")
    if severity not in ("green", "yellow", "red"):
        return CriterionResult(
            name, None, f"aggregate_severity missing/unknown: {severity!r}"
        )
    return CriterionResult(
        name, severity != "red", f"aggregate_severity={severity!r}"
    )


def _check_scale_phase_backlog_owns_kelly_sizing(
    ctx: _EvalContext,
) -> CriterionResult:
    # Intentionally never machine-passes: Phase-C sizing is owned by the
    # Scale-Phase backlog and requires fresh human sign-off. This makes
    # live_full structurally unreachable via the evaluator (stat-review
    # F1: "the empty allowlist must be unreachable, not merely
    # intended-unused").
    return CriterionResult(
        "scale_phase_backlog_owns_kelly_sizing",
        None,
        "human-owned criterion: Scale-Phase backlog must sign off sizing",
    )


_EXTRA_CHECKERS: Mapping[str, Callable[[_EvalContext], CriterionResult]] = {
    "slippage_ks_pvalue_gt_0.05": _check_slippage_ks_pvalue_gt_0_05,
    "hit_rate_inside_c3_bootstrap_ci": _check_hit_rate_inside_c3_bootstrap_ci,
    "kill_switch_never_fired": _check_kill_switch_never_fired,
    "max_dd_live_lt_2x_backtest": _check_max_dd_live_lt_2x_backtest,
    "slippage_ks_reference_backtest_samples": (
        _check_slippage_ks_reference_backtest_samples
    ),
    "drift_window_complete": _check_drift_window_complete,
    "watchdog_status_not_red": _check_watchdog_status_not_red,
    "scale_phase_backlog_owns_kelly_sizing": (
        _check_scale_phase_backlog_owns_kelly_sizing
    ),
}


# ── core evaluation ─────────────────────────────────────────────────


def _variant_row_for(
    drift_artifact: Mapping[str, Any] | None, variant: str
) -> Mapping[str, Any] | None:
    if drift_artifact is None:
        return None
    rows = drift_artifact.get("variants")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("variant") == variant:
            return row
    return None


def _count_closed_trades(
    audit_records: Sequence[Mapping[str, Any]], variant: str, phase: str
) -> int:
    return sum(
        1
        for r in audit_records
        if r.get("variant") == variant
        and r.get("phase") == phase
        and r.get("action") in _CLOSED_ACTIONS
    )


def evaluate_phase_criteria(
    criteria: PhasePassCriteria,
    *,
    variant: str,
    drift_artifact: Mapping[str, Any] | None,
    audit_records: Sequence[Mapping[str, Any]],
    phase_started: date,
    today: date,
    watchdog_report: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> PhaseEvalReport:
    """Evaluate every criterion of ``criteria`` for ``variant``.

    Fail-closed: any criterion that cannot be machine-evaluated
    (``passed=None``) prevents ``all_passed``.
    """
    row = _variant_row_for(drift_artifact, variant)
    ctx = _EvalContext(
        variant=variant,
        phase=criteria.phase,
        variant_row=row,
        audit_records=audit_records,
        watchdog_report=watchdog_report,
    )
    results: list[CriterionResult] = []

    # min_phase_days
    days_in_phase = (today - phase_started).days
    results.append(
        CriterionResult(
            "min_phase_days",
            days_in_phase >= criteria.min_phase_days,
            f"days_in_phase={days_in_phase} required>={criteria.min_phase_days}",
        )
    )

    # min_trades_closed
    n_closed = _count_closed_trades(audit_records, variant, criteria.phase)
    results.append(
        CriterionResult(
            "min_trades_closed",
            n_closed >= criteria.min_trades_closed,
            f"trades_closed={n_closed} required>={criteria.min_trades_closed}",
        )
    )

    # drift-score numeric criteria
    score = row.get("drift_score") if row is not None else None
    score_ok = isinstance(score, (int, float))
    if criteria.max_drift_score_deviation is not None:
        if not score_ok:
            results.append(
                CriterionResult(
                    "max_drift_score_deviation",
                    None,
                    "drift_score unavailable for variant",
                )
            )
        else:
            dev = abs(float(score) - 1.0)
            results.append(
                CriterionResult(
                    "max_drift_score_deviation",
                    dev < criteria.max_drift_score_deviation,
                    f"|drift_score-1|={dev:.6f} required<"
                    f"{criteria.max_drift_score_deviation}",
                )
            )
    if criteria.min_drift_score is not None:
        if not score_ok:
            results.append(
                CriterionResult(
                    "min_drift_score", None, "drift_score unavailable for variant"
                )
            )
        else:
            results.append(
                CriterionResult(
                    "min_drift_score",
                    float(score) >= criteria.min_drift_score,
                    f"drift_score={float(score):.6f} "
                    f"required>={criteria.min_drift_score}",
                )
            )

    # verdict allowlist
    if criteria.require_drift_verdict_in:
        verdict = row.get("verdict") if row is not None else None
        if not isinstance(verdict, str):
            results.append(
                CriterionResult(
                    "require_drift_verdict_in",
                    None,
                    "verdict unavailable for variant",
                )
            )
        else:
            results.append(
                CriterionResult(
                    "require_drift_verdict_in",
                    verdict in criteria.require_drift_verdict_in,
                    f"verdict={verdict!r} "
                    f"allowed={list(criteria.require_drift_verdict_in)}",
                )
            )
    else:
        # Empty allowlist is NOT a free pass — it means the phase has no
        # defined verdict gate, which a fail-closed evaluator must refuse
        # (stat-review F1: Phase-C's empty tuple must be unreachable).
        results.append(
            CriterionResult(
                "require_drift_verdict_in",
                None,
                "no verdict allowlist defined for this phase (fail-closed)",
            )
        )

    # extra criteria via registry (F6)
    for name in criteria.extra:
        checker = _EXTRA_CHECKERS.get(name)
        if checker is None:
            # Unmapped string = silent gate hole. Refuse loudly.
            results.append(
                CriterionResult(
                    name, None, "NO CHECKER REGISTERED for this criterion"
                )
            )
            logger.error(
                "extra criterion %r has no registered checker — gate hole", name
            )
        else:
            results.append(checker(ctx))

    all_passed = all(r.passed is True for r in results)
    when = (now or datetime.now(UTC)).isoformat()
    return PhaseEvalReport(
        phase=criteria.phase,
        variant=variant,
        all_passed=all_passed,
        results=tuple(results),
        computed_at=when,
    )


# ── consumption helper for run_smc_live_incubation ─────────────────


def load_and_validate_eval_report(
    path: Path,
    *,
    target_phase: str,
    expected_variants: Sequence[str] | None = None,
    max_age_days: int = 7,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load a phase-eval report and validate it authorises ``target_phase``.

    Raises :class:`SystemExit` with an operator-readable message when the
    report is missing, stale, not passing, or evaluates the wrong phase.

    When *expected_variants* is a non-empty sequence, the report's
    ``variant`` field must be one of them; otherwise the operator supplied
    an eval report that was produced for a variant that is not being
    traded (W3-3).
    """
    required_phase = PRIOR_PHASE_FOR_ENTRY.get(target_phase)
    if required_phase is None:
        raise SystemExit(
            f"phase={target_phase!r} has no entry-gate mapping; refusing"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"--phase-eval-report {path}: unreadable/invalid JSON ({exc})"
        ) from exc
    if payload.get("phase") != required_phase:
        raise SystemExit(
            f"--phase-eval-report evaluates phase={payload.get('phase')!r} "
            f"but entering {target_phase!r} requires a passing "
            f"{required_phase!r} evaluation"
        )
    if payload.get("all_passed") is not True:
        failing = [
            r.get("criterion")
            for r in payload.get("results", [])
            if r.get("passed") is not True
        ]
        raise SystemExit(
            f"--phase-eval-report all_passed is not true; "
            f"unmet criteria: {failing!r}"
        )
    # W6-1 (stat-review wave 6): a vacuous report with results=[] and
    # all_passed=True must be rejected.  Separately, cross-check every
    # individual criterion — all_passed alone can be spoofed or set by
    # hand without matching per-criterion detail.
    results_raw = payload.get("results")
    if not isinstance(results_raw, list) or len(results_raw) == 0:
        raise SystemExit(
            "--phase-eval-report results list is empty or missing; "
            "an all_passed=true report with no criteria is vacuously forged"
        )
    per_criterion_failing = [
        r.get("criterion")
        for r in results_raw
        if r.get("passed") is not True
    ]
    if per_criterion_failing:
        raise SystemExit(
            f"--phase-eval-report claims all_passed=true but individual "
            f"criteria do not all have passed=true: {per_criterion_failing!r}"
        )
    computed_at_raw = payload.get("computed_at")
    try:
        computed_at = datetime.fromisoformat(str(computed_at_raw))
    except ValueError as exc:
        raise SystemExit(
            f"--phase-eval-report computed_at={computed_at_raw!r} not ISO"
        ) from exc
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=UTC)
    instant = now or datetime.now(UTC)
    age_days = (instant - computed_at).total_seconds() / 86400.0
    if age_days > max_age_days:
        raise SystemExit(
            f"--phase-eval-report is {age_days:.1f} days old "
            f"(max {max_age_days}); re-run scripts/evaluate_phase_criteria.py"
        )
    # W3-3 (stat-review wave 3): prevent cross-variant report substitution.
    if expected_variants:
        report_variant = payload.get("variant")
        if report_variant not in expected_variants:
            raise SystemExit(
                f"--phase-eval-report variant={report_variant!r} is not "
                f"one of the traded variants {sorted(expected_variants)!r}; "
                f"the eval report was produced for a variant that is not "
                f"being traded"
            )
    return payload


# ── CLI ────────────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            # W6-2 (stat-review wave 6): fail-closed on any malformed non-empty
            # line.  A corrupt audit JSONL must never silently drop kill-switch
            # evidence — the gate must refuse rather than produce a vacuous green.
            raise SystemExit(
                f"--audit-jsonl {path}: malformed JSON at line {lineno} "
                f"({exc!s}); re-export the audit log before re-running"
            ) from exc
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _maybe_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Evaluate PhasePassCriteria for one variant against the drift "
            "artifact + incubation audit log + watchdog report. The output "
            "report is required input for run_smc_live_incubation "
            "--phase live_small/live_full."
        )
    )
    p.add_argument(
        "--criteria-phase",
        choices=sorted(PHASE_PASS_CRITERIA),
        required=True,
        help="Which phase's pass criteria to evaluate (the CURRENT phase).",
    )
    p.add_argument("--variant", required=True)
    p.add_argument("--drift-json", type=Path, required=True)
    p.add_argument("--audit-jsonl", type=Path, required=True)
    p.add_argument(
        "--watchdog-json",
        type=Path,
        default=None,
        help="Latest drift_report_<date>.json (needed for drift_window_complete).",
    )
    p.add_argument(
        "--phase-started",
        type=date.fromisoformat,
        required=True,
        help="ISO date the variant entered the current phase.",
    )
    p.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="Override today's date (ISO); defaults to UTC now.",
    )
    p.add_argument("--output", type=Path, required=True)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    today = args.today or datetime.now(UTC).date()
    criteria = PHASE_PASS_CRITERIA[args.criteria_phase]
    report = evaluate_phase_criteria(
        criteria,
        variant=args.variant,
        drift_artifact=_maybe_json(args.drift_json),
        audit_records=_read_jsonl(args.audit_jsonl),
        phase_started=args.phase_started,
        today=today,
        watchdog_report=_maybe_json(args.watchdog_json),
    )
    atomic_write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n",
        args.output,
    )
    logger.info(
        "phase-eval report written: %s (all_passed=%s)",
        args.output,
        report.all_passed,
    )
    return 0 if report.all_passed else 1


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
