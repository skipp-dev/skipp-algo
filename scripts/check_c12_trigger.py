#!/usr/bin/env python3
"""Trigger-gate check for C12 (RL-execution sprint).

C12 is structurally blocked until at least one SMC family has been
running in C8 live incubation for >= 4 weeks with a deterministic
outcome stream. This script makes that condition machine-checkable so
CI / cron can detect when the gate flips to GREEN automatically.

Today's behaviour
-----------------
The script reads ``docs/calibration/calibration_report_public.json``
(produced by the public dashboard pipeline) and inspects the
``status`` field. Until that status moves past ``awaiting_first_run``
and a per-family live-window of >= 28 days is reported, the script
exits with status ``BLOCKED`` and a non-zero return code.

Why a stub today
----------------
The full check requires the C8 outcome stream (live) + per-family
incubation timestamps. Both are scheduled for after C2-C9 ship. This
stub delivers the *contract* now: schema-locked state, deterministic
"BLOCKED" output, and a single point-of-truth for any future
go/no-go decision.

Output format
-------------
- Exit code 0   = trigger gate is GREEN; C12 may proceed
- Exit code 1   = trigger gate is BLOCKED; C12 must not start
- Exit code 2   = unable to evaluate (file missing / malformed)

Stdout is a JSON object with at least ``status`` and ``reasons``.

stdlib only — no heavy imports.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_REPORT = REPO_ROOT / "docs" / "calibration" / "calibration_report_public.json"

MIN_LIVE_DAYS = 28


@dataclass(slots=True)
class TriggerResult:
    status: str  # "GREEN" | "BLOCKED" | "UNEVALUABLE"
    reasons: list[str]
    families_evaluated: int = 0
    families_live_28d_plus: int = 0


def evaluate_trigger(report_path: Path = DASHBOARD_REPORT) -> TriggerResult:
    """Evaluate whether the C12 trigger gate is currently GREEN."""
    if not report_path.is_file():
        return TriggerResult(
            status="UNEVALUABLE",
            reasons=[f"calibration report not found at {report_path}"],
        )
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as exc:
        return TriggerResult(
            status="UNEVALUABLE",
            reasons=[f"calibration report is not valid JSON: {exc}"],
        )

    overall_status = report.get("status", "unknown")
    if overall_status == "awaiting_first_run":
        return TriggerResult(
            status="BLOCKED",
            reasons=[
                "calibration_report_public.json status = 'awaiting_first_run'",
                "no family has produced live outcomes yet",
                "C12 trigger gate requires >= 1 family with >= "
                f"{MIN_LIVE_DAYS} live-incubation days",
            ],
        )

    families = report.get("families") or []
    live_families = [
        f
        for f in families
        if isinstance(f, dict) and float(f.get("live_days", 0)) >= MIN_LIVE_DAYS
    ]
    if live_families:
        return TriggerResult(
            status="GREEN",
            reasons=[
                f"{len(live_families)} family/families live for "
                f">= {MIN_LIVE_DAYS} days"
            ],
            families_evaluated=len(families),
            families_live_28d_plus=len(live_families),
        )

    return TriggerResult(
        status="BLOCKED",
        reasons=[
            "no family has reached the 28-day live-incubation threshold",
            f"families inspected: {len(families)}",
        ],
        families_evaluated=len(families),
        families_live_28d_plus=0,
    )


def main() -> int:
    result = evaluate_trigger()
    payload = {
        "status": result.status,
        "reasons": result.reasons,
        "families_evaluated": result.families_evaluated,
        "families_live_28d_plus": result.families_live_28d_plus,
        "min_live_days_required": MIN_LIVE_DAYS,
    }
    print(json.dumps(payload, indent=2))
    if result.status == "GREEN":
        return 0
    if result.status == "BLOCKED":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
