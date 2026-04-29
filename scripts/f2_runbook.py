"""Consolidated F2 operator runbook.

One-shot Markdown report combining:

  - current artifact status (via :func:`scripts.f2_inspect_status.build_status`)
  - 7-day weekly digest (via :func:`scripts.f2_weekly_digest.build_digest`)
  - latest rollback-history ring entries

Designed for pasting into Slack/email or attaching to a daily standup.
The companion JSON manifest (schema_version=1) is machine-readable for
follow-up automation.

Exit codes
----------
  0 = runbook generated
  1 = I/O or config error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.f2_inspect_status import build_status
from scripts.f2_weekly_digest import build_digest
from scripts.smc_atomic_write import atomic_write_text

RUNBOOK_SCHEMA_VERSION = 1
DEFAULT_WINDOW_DAYS = 7
DEFAULT_RING_TAIL = 5


def _load_ring_tail(history_path: Path, n: int) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data[-n:]


def build_runbook(
    *,
    spec_path: Path,
    revert_journal: Path,
    reports_dir: Path,
    history_path: Path,
    window_days: int = DEFAULT_WINDOW_DAYS,
    ring_tail: int = DEFAULT_RING_TAIL,
) -> dict[str, Any]:
    """Assemble the runbook manifest."""
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    if ring_tail < 0:
        raise ValueError("ring_tail must be >= 0")
    status = build_status(
        spec_path=spec_path,
        revert_journal=revert_journal,
        reports_dir=reports_dir,
    )
    digest = build_digest(reports_dir=reports_dir, window_days=window_days)
    ring = _load_ring_tail(history_path, ring_tail)
    return {
        "schema_version": RUNBOOK_SCHEMA_VERSION,
        "window_days": window_days,
        "ring_tail": ring_tail,
        "status": status,
        "weekly_digest": digest,
        "recent_ring": ring,
    }


def render_markdown(rb: dict[str, Any]) -> str:
    """Format the runbook as a pasteable Markdown report."""
    lines: list[str] = []
    lines.append("# F2 Operator Runbook")
    lines.append("")

    st = rb["status"]
    art = st.get("artifact", {}) or {}
    rj = st.get("revert_journal", {}) or {}
    pj = st.get("promote_journal", {}) or {}
    latest = st.get("latest_report") or {}
    lines.append("## Status")
    lines.append("")
    lines.append(f"- artifact status: `{art.get('status', 'unknown')}`")
    lines.append(f"- artifact path: `{art.get('path', '—')}`")
    lines.append(f"- revert journal len: {rj.get('len', 0)}")
    lines.append(f"- promote journal len: {pj.get('len', 0)}")
    if latest:
        lines.append(
            f"- latest report: {latest.get('date', '—')} "
            f"decision=`{latest.get('decision', '—')}`"
        )
    lines.append("")

    dg = rb["weekly_digest"]
    lines.append(f"## Weekly digest ({rb['window_days']}d)")
    lines.append("")
    lines.append(f"- reports in window: {dg.get('len', 0)}")
    decisions = dg.get("decisions", {}) or {}
    if decisions:
        lines.append("- decisions: " + ", ".join(
            f"{k}={v}" for k, v in sorted(decisions.items())
        ))
    sprt = dg.get("sprt_decisions", {}) or {}
    if sprt:
        lines.append("- sprt: " + ", ".join(
            f"{k}={v}" for k, v in sorted(sprt.items())
        ))
    lines.append(f"- consecutive_worse: {dg.get('consecutive_worse', 0)}")
    lines.append(f"- consecutive_better: {dg.get('consecutive_better', 0)}")
    lines.append("")

    ring = rb["recent_ring"]
    lines.append(f"## Recent ring (tail {rb['ring_tail']})")
    lines.append("")
    if not ring:
        lines.append("_(empty)_")
    else:
        lines.append("| date | decision | reason |")
        lines.append("| --- | --- | --- |")
        for entry in ring:
            date = entry.get("date", "—")
            decision = entry.get("decision", "—")
            reason = (entry.get("reason") or "").replace("|", "\\|")
            if len(reason) > 60:
                reason = reason[:57] + "..."
            lines.append(f"| {date} | `{decision}` | {reason} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Consolidated F2 operator runbook (status + weekly digest + ring).",
    )
    parser.add_argument("--spec", type=Path, required=True,
                        help="Path to the F2 spec JSON.")
    parser.add_argument("--revert-journal", type=Path, required=True,
                        help="Path to the revert journal JSONL.")
    parser.add_argument("--reports-dir", type=Path, required=True,
                        help="Directory of f2_promotion_gate_*.json reports.")
    parser.add_argument("--history", type=Path, required=True,
                        help="Path to the rollback-history ring JSON.")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"Weekly digest window (default: {DEFAULT_WINDOW_DAYS}).")
    parser.add_argument("--ring-tail", type=int, default=DEFAULT_RING_TAIL,
                        help=f"How many ring entries to include (default: {DEFAULT_RING_TAIL}).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional path to write the manifest JSON.")
    parser.add_argument("--format", choices=("md", "json"), default="md",
                        help="Stdout format (default: md).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress stdout body; still writes --output if given.")
    args = parser.parse_args(argv)

    try:
        rb = build_runbook(
            spec_path=args.spec,
            revert_journal=args.revert_journal,
            reports_dir=args.reports_dir,
            history_path=args.history,
            window_days=args.window_days,
            ring_tail=args.ring_tail,
        )
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(rb, indent=2) + "\n", args.output)

    if not args.quiet:
        if args.format == "md":
            print(render_markdown(rb))
        else:
            print(json.dumps(rb, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
