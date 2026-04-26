#!/usr/bin/env python3
"""Trigger-gate check for C12 (RL-execution sprint).

C12 is structurally blocked until at least one SMC family has been
running in C8 live incubation **deep enough to support an RL-policy
hand-off**. This script makes that condition machine-checkable so CI
/ cron can detect when the gate flips to GREEN automatically.

What the gate requires
----------------------
Per the C8 runbook (``docs/c8_live_incubation_runbook.md``) the
"externally sellable" track-record state is **Phase-B (live_small)**
not Phase-A (paper). Promoting to RL-execution against a paper-only
track record would re-introduce curve-fit risk. The trigger therefore
requires **per family** all of:

1. ``live_days >= MIN_LIVE_DAYS`` (default 90, mirrors
   ``PHASE_B_CRITERIA.min_phase_days`` from
   :mod:`scripts.run_smc_live_incubation`).
2. ``n_trades >= MIN_LIVE_TRADES`` (default 30, mirrors
   ``PHASE_B_CRITERIA.min_trades_closed``).
3. ``kill_switch_fires == 0`` (Phase-B halt-trigger contract).
4. ``drift_verdict in {"pass", "acceptable"}`` (drift-watchdog
   verdict surfaced by C9).

Any family that satisfies all four passes the gate. ``UNEVALUABLE``
is reserved for *schema violations* (file missing, malformed JSON,
``families`` not a list); ``BLOCKED`` is the default deterministic
'no family qualifies yet' output.

Output format
-------------
- Exit code 0   = trigger gate is GREEN; C12 may proceed
- Exit code 1   = trigger gate is BLOCKED; C12 must not start
- Exit code 2   = unable to evaluate (file missing / malformed schema)

Stdout is a JSON object with at least ``status``, ``reasons``,
``families_evaluated``, ``families_live_qualified``,
``min_live_days_required``, ``min_live_trades_required``.

stdlib only — no heavy imports.

CLI
---
::

    python scripts/check_c12_trigger.py
    python scripts/check_c12_trigger.py --report-path PATH
    CALIBRATION_REPORT_PATH=PATH python scripts/check_c12_trigger.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DASHBOARD_REPORT = (
    REPO_ROOT / "docs" / "calibration" / "calibration_report_public.json"
)

# Mirrors PHASE_B_CRITERIA from scripts.run_smc_live_incubation.
# Pinned in tests/test_c12_trigger_phase_b_alignment.py so it cannot
# silently drift from the runbook contract.
MIN_LIVE_DAYS = 90
MIN_LIVE_TRADES = 30
ACCEPTABLE_DRIFT_VERDICTS = frozenset({"pass", "acceptable"})


@dataclass(slots=True)
class TriggerResult:
    status: str  # "GREEN" | "BLOCKED" | "UNEVALUABLE"
    reasons: list[str]
    families_evaluated: int = 0
    families_live_qualified: int = 0
    invalid_families: int = 0
    failure_breakdown: dict[str, int] = field(default_factory=dict)


def _coerce_float(value: object) -> float | None:
    """Best-effort coerce; ``None``/``"N/A"``/missing/dict -> None."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    f = _coerce_float(value)
    if f is None:
        return None
    return int(f)


def _evaluate_family(family: dict) -> tuple[bool, list[str]]:
    """Return (passes_gate, list_of_failure_reasons)."""
    failures: list[str] = []

    live_days = _coerce_float(family.get("live_days"))
    if live_days is None:
        failures.append("live_days_unparseable")
    elif live_days < MIN_LIVE_DAYS:
        failures.append("live_days_below_threshold")

    n_trades = _coerce_int(family.get("n_trades"))
    if n_trades is None:
        failures.append("n_trades_missing")
    elif n_trades < MIN_LIVE_TRADES:
        failures.append("n_trades_below_threshold")

    kill_switch = _coerce_int(family.get("kill_switch_fires"))
    if kill_switch is None:
        failures.append("kill_switch_fires_missing")
    elif kill_switch != 0:
        failures.append("kill_switch_has_fired")

    verdict_raw = family.get("drift_verdict")
    if not isinstance(verdict_raw, str):
        failures.append("drift_verdict_missing")
    elif verdict_raw not in ACCEPTABLE_DRIFT_VERDICTS:
        failures.append("drift_verdict_unacceptable")

    return (not failures, failures)


def evaluate_trigger(
    report_path: Path = DEFAULT_DASHBOARD_REPORT,
) -> TriggerResult:
    """Evaluate whether the C12 trigger gate is currently GREEN."""
    if not report_path.is_file():
        return TriggerResult(
            status="UNEVALUABLE",
            reasons=[f"calibration report not found at {report_path}"],
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        return TriggerResult(
            status="UNEVALUABLE",
            reasons=[f"calibration report is not valid UTF-8: {exc}"],
        )
    except json.JSONDecodeError as exc:
        return TriggerResult(
            status="UNEVALUABLE",
            reasons=[f"calibration report is not valid JSON: {exc}"],
        )
    if not isinstance(report, dict):
        return TriggerResult(
            status="UNEVALUABLE",
            reasons=["calibration report root is not a JSON object"],
        )

    overall_status = report.get("status", "unknown")
    if overall_status == "awaiting_first_run":
        return TriggerResult(
            status="BLOCKED",
            reasons=[
                "calibration_report_public.json status = 'awaiting_first_run'",
                "no family has produced live outcomes yet",
                f"C12 trigger gate requires >= 1 family with >= "
                f"{MIN_LIVE_DAYS} live-incubation days, "
                f">= {MIN_LIVE_TRADES} closed trades, "
                "kill_switch_fires == 0, and drift_verdict in "
                f"{sorted(ACCEPTABLE_DRIFT_VERDICTS)}",
            ],
        )

    families_raw = report.get("families")
    if families_raw is None:
        families: list = []
    elif not isinstance(families_raw, list):
        # Schema violation -> UNEVALUABLE, NOT BLOCKED. A bad payload
        # should never silently keep the gate closed; a human must look.
        return TriggerResult(
            status="UNEVALUABLE",
            reasons=[
                f"'families' must be a list, got {type(families_raw).__name__}",
            ],
        )
    else:
        families = families_raw

    invalid_families = 0
    qualified: list[dict] = []
    failure_breakdown: dict[str, int] = {}

    for f in families:
        if not isinstance(f, dict):
            invalid_families += 1
            continue
        passes, failures = _evaluate_family(f)
        if passes:
            qualified.append(f)
        else:
            for reason in failures:
                failure_breakdown[reason] = failure_breakdown.get(reason, 0) + 1

    if qualified:
        return TriggerResult(
            status="GREEN",
            reasons=[
                f"{len(qualified)} family/families satisfied all gate "
                f"criteria (>= {MIN_LIVE_DAYS}d, >= {MIN_LIVE_TRADES} trades, "
                "kill_switch=0, drift in pass/acceptable)"
            ],
            families_evaluated=len(families),
            families_live_qualified=len(qualified),
            invalid_families=invalid_families,
            failure_breakdown=failure_breakdown,
        )

    reasons = [
        "no family satisfied all gate criteria",
        f"families inspected: {len(families)}",
    ]
    if invalid_families:
        reasons.append(
            f"{invalid_families} non-dict family entries skipped"
        )
    if failure_breakdown:
        reasons.append(
            "failure breakdown: "
            + ", ".join(
                f"{k}={v}" for k, v in sorted(failure_breakdown.items())
            )
        )
    return TriggerResult(
        status="BLOCKED",
        reasons=reasons,
        families_evaluated=len(families),
        families_live_qualified=0,
        invalid_families=invalid_families,
        failure_breakdown=failure_breakdown,
    )


def _resolve_report_path(cli_path: str | None) -> Path:
    """Precedence: CLI flag > CALIBRATION_REPORT_PATH env > default."""
    if cli_path:
        return Path(cli_path).expanduser().resolve()
    env_path = os.environ.get("CALIBRATION_REPORT_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_DASHBOARD_REPORT


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the C12 trigger gate. Exits 0=GREEN, 1=BLOCKED, "
            "2=UNEVALUABLE."
        )
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help=(
            "Path to calibration_report_public.json. Defaults to the "
            "committed dashboard artefact; can also be set via the "
            "CALIBRATION_REPORT_PATH env var."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report_path = _resolve_report_path(args.report_path)
    result = evaluate_trigger(report_path)
    payload = {
        "status": result.status,
        "reasons": result.reasons,
        "families_evaluated": result.families_evaluated,
        "families_live_qualified": result.families_live_qualified,
        "invalid_families": result.invalid_families,
        "failure_breakdown": result.failure_breakdown,
        "min_live_days_required": MIN_LIVE_DAYS,
        "min_live_trades_required": MIN_LIVE_TRADES,
        "report_path": str(report_path),
    }
    print(json.dumps(payload, indent=2))
    if result.status == "GREEN":
        return 0
    if result.status == "BLOCKED":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
