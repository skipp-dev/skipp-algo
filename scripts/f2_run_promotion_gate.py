"""F2 promotion-gate CLI orchestrator (plan §2.3 F2 + §2.4 G3).

Single entry point that ties together:

1. ``scripts.run_ab_comparison.compare`` — produces the digest with the
   embedded ``sprt`` block.
2. ``scripts.f2_experiment_spec.evaluate_promotion`` — maps the digest +
   rollback history to one of ``{promote, hold, rollback,
   insufficient_data}`` plus the canonical action list.

Inputs
------
* ``--spec``           Path to the F2 experiment spec JSON.
* ``--control-dir``    Benchmark artifact dir for the control arm
                       (``benchmark_run_manifest.json`` + per-pair scoring).
* ``--treatment-dir``  Benchmark artifact dir for the treatment arm.
* ``--rollback-history`` Optional path to a JSON list of historical
                       ``treatment - control`` deltas for the configured
                       comparison metric. Used by the rollback gate.
* ``--output``         Optional output path for the promotion-gate report
                       JSON. Default: stdout only.

Outputs
-------
A schema-pinned JSON document (``schema_version=1``) carrying the
promotion-gate decision, the SPRT terminal report, the KPI deltas, the
rollback-gate evaluation and the resolved action list. Designed to be
checked in as a daily artifact when the rolling-benchmark workflow
accumulates dual-arm output.

Exit codes
----------
0  : decision in {promote, hold, rollback, insufficient_data}; report
     written.
1  : configuration error (missing spec, missing artifact dir, etc.).
2  : decision == "rollback"; useful as a CI signal so the workflow can
     trigger the GitHub-Issue-Ping per plan §2.4 G2.
"""

from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01): bootstrap root logging so the
# logger.info(...) progress messages this entry point emits actually
# surface in CI logs (default WARNING-only handler would drop them).
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v5a12_sys
    from pathlib import Path as _v5a12_Path

    _v5a12_sys.path.insert(0, str(_v5a12_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]


import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from scripts.f2_experiment_spec import (
    F2Spec,
    evaluate_promotion,
    load_f2_spec,
)
from scripts.generate_performance_report import load_benchmark
from scripts.run_ab_comparison import compare
from scripts.smc_atomic_write import atomic_write_text

REPORT_SCHEMA_VERSION = 1


def _load_rollback_history(path: Path | None) -> list[float]:
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"rollback-history file {path} must contain a JSON list, got {type(raw).__name__}"
        )
    return [float(x) for x in raw]


def _pair_dicts(pairs: list[Any]) -> list[dict[str, Any]]:
    """Convert PairReport dataclasses to the dict shape compare() consumes.

    Note on units: ``PairReport.hit_rate`` is loaded from scoring summaries
    as a fraction in ``[0, 1]`` (the on-disk JSON convention from
    ``smc_signal_quality``), but the downstream comparison + SPRT wiring
    treats ``hit_rate_pct`` as a percent in ``[0, 100]``. We multiply by
    100 here so the convention is consistent across the pipeline.
    """
    out: list[dict[str, Any]] = []
    for p in pairs:
        out.append({
            "symbol": p.symbol,
            "timeframe": p.timeframe,
            "n_events": p.n_events,
            "brier": p.brier,
            "hit_rate_pct": p.hit_rate * 100.0,
            "calibrated_brier": p.calibrated_brier,
            "calibrated_ece": p.calibrated_ece,
            "ensemble_score": p.ensemble_score,
        })
    return out


def run_promotion_gate(
    *,
    spec: F2Spec,
    control_dir: Path,
    treatment_dir: Path,
    rollback_history: list[float],
) -> dict[str, Any]:
    """Compute the F2 promotion-gate report for two benchmark artifact dirs."""
    control_pairs = _pair_dicts(load_benchmark(control_dir))
    treatment_pairs = _pair_dicts(load_benchmark(treatment_dir))
    if not control_pairs:
        raise ValueError(f"no benchmark pairs in control_dir={control_dir}")
    if not treatment_pairs:
        raise ValueError(f"no benchmark pairs in treatment_dir={treatment_dir}")

    # 2026-06-10 audit: pass the spec's pre-registered SPRT parameters
    # into the comparison. Before this, compare() silently used the
    # hardcoded module defaults (p0=0.55/p1=0.60) and the spec's
    # recalibrated values were dead config.
    digest = compare(control_pairs, treatment_pairs, spec.name, sprt_config=spec.sprt)

    # W6-3 (stat-review wave 6): rollback history must include the current
    # run's delta so evaluate_promotion sees a trailing window ending TODAY,
    # not yesterday.  The workflow appends the delta AFTER the gate runs,
    # creating an off-by-one that delays rollback detection by one day.
    # Extract the current delta from the digest and append it here.
    comparison_metric = spec.rollback_gate.comparison_metric
    current_delta: float | None = None
    for _row in digest.get("metrics") or []:
        if _row.get("metric") == comparison_metric:
            _val = _row.get("delta")
            if _val is not None:
                try:
                    _f = float(_val)
                    if not math.isnan(_f):
                        current_delta = _f
                except (TypeError, ValueError):
                    pass
            break
    full_daily_deltas = (
        rollback_history + [current_delta]
        if current_delta is not None
        else rollback_history
    )
    gate = evaluate_promotion(digest, spec, daily_deltas=full_daily_deltas)

    # ── Spec-status guard (audit findings C1/C2/C3 follow-up) ────────────
    # When ``spec.status != "live"`` the underlying statistical apparatus
    # is known-broken (see docs/f2_contextual_promotion_decision_2026-04-21.md
    # ``2026-04-23 — G3 Dual-Arm Wiring Operationalized`` addendum).
    # Force the decision to ``hold`` and surface a structured warning so
    # the promote pathway cannot fire by accident before PR #43/#44 land.
    warnings: list[str] = []
    decision = gate["decision"]
    reason = gate["reason"]
    actions = list(gate["actions"])
    if spec.status != "live":
        if decision == "promote":
            decision = "hold"
            reason = (
                f"spec.status={spec.status!r} (not 'live'); promote path "
                "disabled per audit findings C1/C2/C3"
            )
            actions = ["Keep static global weights — promote disabled."]
        warnings.append(
            f"spec.status={spec.status!r}; statistical basis pending "
            "(A1/A2/A3 — see PR #43/#44). Brier/ECE deltas may be "
            f"in-sample-biased; SPRT is single-arm vs fixed p0={spec.sprt.p0}."
        )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "experiment": spec.name,
        "plan_reference": spec.plan_reference,
        "spec_status": spec.status,
        "decision": decision,
        "reason": reason,
        "actions": actions,
        "warnings": warnings,
        "sprt": digest.get("sprt"),
        "kpi_metrics": digest.get("metrics"),
        # W6-3: expose the effective history window (includes today's delta)
        # so the audit trail shows exactly what the rollback gate evaluated.
        "rollback_history_len": len(full_daily_deltas),
        "rollback_history_includes_current_run": current_delta is not None,
        # evaluate_promotion does not return a rollback_triggered key; derive
        # it from the decision so downstream consumers have a stable bool flag.
        "rollback_triggered": decision == "rollback",
        "spec": {
            "control_artifact": str(spec.control_artifact),
            "treatment_artifact": str(spec.treatment_artifact),
            "min_events_per_arm": spec.min_events_per_arm,
            "min_days": spec.min_days,
        },
    }


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    parser = argparse.ArgumentParser(
        description="F2 contextual-promotion gate orchestrator (plan §2.3 F2)"
    )
    parser.add_argument("--spec", type=Path, required=True,
                        help="Path to the F2 experiment spec JSON.")
    parser.add_argument("--control-dir", type=Path, required=True,
                        help="Benchmark artifact dir for the control arm.")
    parser.add_argument("--treatment-dir", type=Path, required=True,
                        help="Benchmark artifact dir for the treatment arm.")
    parser.add_argument("--rollback-history", type=Path, default=None,
                        help=("Optional JSON list of historical "
                              "treatment-control deltas for the rollback gate."))
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional output path for the promotion-gate JSON.")
    args = parser.parse_args(argv)

    try:
        spec = load_f2_spec(args.spec)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: failed to load spec {args.spec}: {exc}", file=sys.stderr)
        return 1

    if not args.control_dir.exists():
        print(f"ERROR: control_dir does not exist: {args.control_dir}", file=sys.stderr)
        return 1
    if not args.treatment_dir.exists():
        print(f"ERROR: treatment_dir does not exist: {args.treatment_dir}", file=sys.stderr)
        return 1

    try:
        rollback_history = _load_rollback_history(args.rollback_history)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: failed to load rollback history: {exc}", file=sys.stderr)
        return 1

    try:
        report = run_promotion_gate(
            spec=spec,
            control_dir=args.control_dir,
            treatment_dir=args.treatment_dir,
            rollback_history=rollback_history,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: failed to compute promotion gate: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(report, indent=2) + "\n", args.output)
    print(json.dumps(report, indent=2))

    if report["decision"] == "rollback":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
