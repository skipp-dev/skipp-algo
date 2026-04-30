"""Render a normalized gate summary for ``GITHUB_STEP_SUMMARY``.

Reads a release-gate or evidence-summary JSON report and emits a
Markdown table with consistent columns, enforcement status labels,
and gate-level verdicts so that CI summaries are readable without
log archaeology.

Usage
-----
Called from workflow YAML steps::

    python scripts/render_ci_gate_summary.py \\
        --report artifacts/ci/smc_release_gates_report.json \\
        --enforcement hard

Or for deeper/advisory lanes::

    python scripts/render_ci_gate_summary.py \\
        --report artifacts/ci/smc_deeper_health_report.json \\
        --enforcement advisory
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Enforcement labels
# ---------------------------------------------------------------------------

ENFORCEMENT_HARD = "hard"
ENFORCEMENT_ADVISORY = "advisory"
ENFORCEMENT_NOT_ENFORCED = "not-enforced"

_ENFORCEMENT_ICONS = {
    ENFORCEMENT_HARD: "\U0001F6D1",        # 🛑
    ENFORCEMENT_ADVISORY: "\u26A0\uFE0F",  # ⚠️
    ENFORCEMENT_NOT_ENFORCED: "\u2139\uFE0F",  # ℹ️
}


# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------


def _load_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Report root must be a JSON object: {path}")
    return payload


def _gate_rows_from_release(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract gate rows from a release-gates report."""
    gates = report.get("gates", [])
    if not isinstance(gates, list):
        return []
    return [g for g in gates if isinstance(g, dict)]


def _gate_rows_from_evidence(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Synthesize gate rows from an evidence summary."""
    rows: list[dict[str, Any]] = []
    criteria = report.get("criteria", {})
    green_ready = report.get("green_ready", False)

    rows.append({
        "name": "evidence_readiness",
        "status": "ok" if green_ready else "fail",
        "blocking": False,
        "details": {
            "green_ready": green_ready,
            "not_ready_reasons": report.get("not_ready_reasons", []),
        },
    })

    deeper_ok = report.get("deeper_ok_runs_in_window", 0)
    min_deeper = criteria.get("min_deeper_ok_runs", 0)
    rows.append({
        "name": "deeper_runs_in_window",
        "status": "ok" if deeper_ok >= min_deeper else "warn",
        "blocking": False,
        "details": {"count": deeper_ok, "required": min_deeper},
    })

    release_ok = report.get("release_ok_runs_in_window", 0)
    min_release = criteria.get("min_release_ok_runs", 0)
    rows.append({
        "name": "release_runs_in_window",
        "status": "ok" if release_ok >= min_release else "warn",
        "blocking": False,
        "details": {"count": release_ok, "required": min_release},
    })

    return rows


def extract_gate_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract or synthesize gate rows from any recognized report kind."""
    kind = str(report.get("report_kind", "")).strip()
    if kind in ("release_gates", "post_release_validation"):
        return _gate_rows_from_release(report)
    if kind == "gate_evidence_summary":
        return _gate_rows_from_evidence(report)
    # Fallback: try gates list
    gates = report.get("gates", [])
    if isinstance(gates, list) and gates:
        return [g for g in gates if isinstance(g, dict)]
    return []


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "ok": "\u2705",     # ✅
    "warn": "\u26A0\uFE0F",  # ⚠️
    "fail": "\u274C",   # ❌
}


def render_gate_summary_markdown(
    gates: list[dict[str, Any]],
    *,
    enforcement: str,
    report_kind: str = "",
    overall_status: str = "",
) -> str:
    """Render a Markdown gate summary table."""
    lines: list[str] = []

    enforcement_icon = _ENFORCEMENT_ICONS.get(enforcement, "")
    enforcement_label = enforcement.upper().replace("-", " ")
    title_status = _STATUS_ICONS.get(overall_status, "")

    lines.append(f"### {title_status} Gate Summary — {enforcement_icon} {enforcement_label}")
    lines.append("")
    lines.append("| Gate | Status | Blocking | Detail |")
    lines.append("|------|--------|----------|--------|")

    for gate in gates:
        name = gate.get("name", "unknown")
        status = str(gate.get("status", "unknown")).lower()
        blocking = gate.get("blocking", True)
        icon = _STATUS_ICONS.get(status, "\u2753")  # ❓
        blocking_label = "yes" if blocking else "no"

        # Compact detail — pick the most useful single-line summary.
        detail = ""
        details = gate.get("details", {})
        if gate.get("ci_mode_downgraded"):
            reason = gate.get("ci_mode_downgrade_reason", "data_absent")
            detail = f"downgraded ({reason})"
        elif gate.get("tv_failure_class"):
            detail = f"tv: {gate['tv_failure_class']}"
        elif isinstance(details.get("message"), str):
            detail = details["message"][:80]
        elif isinstance(details.get("failures"), list) and details["failures"]:
            codes = [str(f.get("code", "")) for f in details["failures"][:3]]
            detail = ", ".join(c for c in codes if c)
        elif isinstance(details.get("overall_status"), str):
            detail = details["overall_status"]
        elif isinstance(details.get("pairs_checked"), int):
            detail = f"{details['pairs_checked']} pairs"

        lines.append(f"| {name} | {icon} {status} | {blocking_label} | {detail} |")

    lines.append("")
    return "\n".join(lines)


def write_to_step_summary(content: str) -> bool:
    """Append *content* to ``$GITHUB_STEP_SUMMARY`` if available."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary_path:
        return False
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(content)
        f.write("\n")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render normalized CI gate summary.")
    parser.add_argument("--report", required=True, help="Path to gate or evidence JSON report.")
    parser.add_argument(
        "--enforcement",
        choices=[ENFORCEMENT_HARD, ENFORCEMENT_ADVISORY, ENFORCEMENT_NOT_ENFORCED],
        default=ENFORCEMENT_ADVISORY,
        help="Enforcement level label for the summary header.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = Path(args.report)

    if not path.exists():
        print(f"Report not found: {path}", file=sys.stderr)
        return 1

    report = _load_report(path)
    gates = extract_gate_rows(report)
    overall = str(report.get("overall_status", "unknown")).lower()
    kind = str(report.get("report_kind", "")).strip()

    md = render_gate_summary_markdown(
        gates,
        enforcement=args.enforcement,
        report_kind=kind,
        overall_status=overall,
    )

    if not write_to_step_summary(md):
        # Not in CI — print to stdout for local testing.
        print(md)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
