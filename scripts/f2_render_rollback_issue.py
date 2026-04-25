"""Render a GitHub Issue body from an F2 promotion-gate JSON report.

Plan reference:
  smc_improvement_plan_q3_q4_2026-04-20.md §2.4 G2:
    "If Auto-Tuning-Arm is worse than Static-Arm in 2 consecutive
     runs -> automatic Revert + GitHub-Issue-Ping."

This module is the deterministic side of that "Issue-Ping": given the
machine-readable promotion-gate report (produced by
:mod:`scripts.f2_run_promotion_gate`), it emits the title and Markdown
body for an Issue that an operator can immediately act on. The
``.github/workflows/f2-promotion-gate-daily.yml`` workflow pipes this
output to ``gh issue create`` when the gate exits with rc=2.

Pure-Python, no network. Tested.
"""

from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ISSUE_LABEL = "f2-rollback"
TITLE_PREFIX = "[F2 rollback]"


def _fmt_metric_row(row: dict[str, Any]) -> str:
    metric = row.get("metric", "?")
    control = row.get("control", "?")
    treatment = row.get("treatment", "?")
    delta = row.get("delta", "?")
    return f"| `{metric}` | {control} | {treatment} | {delta} |"


def render_title(report: dict[str, Any], *, date: str | None = None) -> str:
    decision = report.get("decision", "unknown")
    if date:
        return f"{TITLE_PREFIX} {decision} on {date}"
    return f"{TITLE_PREFIX} {decision}"


def render_body(
    report: dict[str, Any],
    *,
    date: str | None = None,
    workflow_run_url: str | None = None,
    report_path: str | None = None,
) -> str:
    """Render the Markdown body for the rollback Issue."""
    decision = report.get("decision", "unknown")
    metrics = report.get("kpi_metrics") or []
    sprt = report.get("sprt") or {}
    rollback_window = report.get("rollback_window") or []

    lines: list[str] = []
    lines.append(f"# F2 contextual promotion-gate: **{decision}**")
    lines.append("")
    lines.append(
        "Plan reference: "
        "`smc_improvement_plan_q3_q4_2026-04-20.md` §2.4 G2 "
        "(rollback gate) + §2.3 F2 (contextual promotion)."
    )
    lines.append("")
    if date:
        lines.append(f"- **Run date:** `{date}`")
    if workflow_run_url:
        lines.append(f"- **Workflow run:** {workflow_run_url}")
    if report_path:
        lines.append(f"- **Promotion-gate report:** `{report_path}`")
    lines.append(
        f"- **Decision:** `{decision}` "
        "(workflow exit code 2 = rollback, fired the §2.4 G2 ping rule)"
    )
    lines.append("")

    if metrics:
        lines.append("## KPI deltas (treatment − control)")
        lines.append("")
        lines.append("| Metric | Control | Treatment | Δ (T−C) |")
        lines.append("|---|---:|---:|---:|")
        for row in metrics:
            lines.append(_fmt_metric_row(row))
        lines.append("")

    if sprt:
        lines.append("## SPRT terminal decision")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        for key in ("decision", "n", "k", "llr", "p0", "p1", "alpha", "beta"):
            if key in sprt:
                lines.append(f"| `{key}` | {sprt[key]} |")
        lines.append("")

    if rollback_window:
        lines.append("## Rollback-history window")
        lines.append("")
        lines.append(
            "Trailing window of `calibrated_brier` deltas the gate "
            "evaluated (positive = treatment worse):"
        )
        lines.append("")
        lines.append("```")
        lines.append(json.dumps(list(rollback_window), indent=2))
        lines.append("```")
        lines.append("")

    lines.append("## Operator runbook")
    lines.append("")
    lines.append(
        "1. Confirm the rollback decision by inspecting the uploaded "
        "promotion-gate JSON artifact and the linked workflow run."
    )
    lines.append(
        "2. The contextual calibration JSON has already been demoted "
        "to `status=shadow` automatically by the daily workflow "
        "(`scripts/f2_revert_contextual_weights.py`). Review the "
        "`revert_journal.jsonl` and the archived copy under "
        "`artifacts/ci/f2/contextual_calibration.archive/` in the "
        "uploaded artifact. Regenerate the Pine export only if the "
        "shipping artifact has changed."
    )
    lines.append(
        "3. After the manual review concludes, RESET the daily ring "
        "with `python scripts/f2_rotate_rollback_history.py "
        "--history artifacts/ci/f2/rollback_history.json` so the next "
        "day's gate does not immediately re-fire on stale history."
    )
    lines.append(
        "4. Close this Issue once steps 1–3 are complete (or convert "
        "it to a postmortem if a real regression is confirmed)."
    )
    lines.append("")
    lines.append(f"_Auto-filed by `f2-promotion-gate-daily` workflow. Label: `{ISSUE_LABEL}`._")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a rollback-Issue title+body from a promotion-gate report."
    )
    parser.add_argument("--report", type=Path, required=True,
                        help="Path to the promotion-gate JSON report.")
    parser.add_argument("--date", type=str, default=None,
                        help="Run date (YYYY-MM-DD) for the Issue title.")
    parser.add_argument("--workflow-run-url", type=str, default=None,
                        help="Optional URL to the failing workflow run.")
    parser.add_argument("--report-path", type=str, default=None,
                        help="Display path of the report (for the Issue body).")
    parser.add_argument("--title-out", type=Path, default=None,
                        help="If set, write the Issue title to this file.")
    parser.add_argument("--body-out", type=Path, default=None,
                        help="If set, write the Issue body to this file.")
    args = parser.parse_args(argv)

    if not args.report.exists():
        print(f"ERROR: report does not exist: {args.report}", file=sys.stderr)
        return 1
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: failed to parse {args.report}: {exc}", file=sys.stderr)
        return 1

    title = render_title(report, date=args.date)
    body = render_body(
        report,
        date=args.date,
        workflow_run_url=args.workflow_run_url,
        report_path=args.report_path,
    )

    if args.title_out:
        atomic_write_text(title + "\n", args.title_out)
    if args.body_out:
        atomic_write_text(body + "\n", args.body_out)
    if not args.title_out and not args.body_out:
        # Default to stdout: title on first line, blank, then body.
        print(title)
        print()
        print(body)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
