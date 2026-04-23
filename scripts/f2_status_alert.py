"""F2 promotion-gate status alert (audit M8 follow-up).

Scans ``artifacts/reports/f2_promotion_gate_*.json`` and emits a
GitHub Actions ``::warning::`` annotation when the most-recent
contiguous run of reports has been stuck on a non-progressing
decision for at least ``--threshold`` consecutive days.

Non-progressing decisions:

  * ``skipped``           — locate step did not find dual-arm dirs
  * ``insufficient_data`` — SPRT did not terminate this run
  * ``hold``              — gate explicitly held (incl. spec-status-block)

These are individually expected; a *streak* of them silently means
the 30-day promotion countdown is not advancing and on-call should
look. The script is intentionally side-effect-light: it never opens
or comments on issues — that is the rollback path's job. It only
prints the warning and a small structured JSON to stdout for any
follow-up tooling.

Exit codes
----------

  * 0 — wrote alert (or no alert needed); never fails CI.
  * 1 — argument / IO error.

Schema (stdout JSON)
--------------------

::

    {
      "schema_version": 1,
      "threshold": 3,
      "streak": 5,
      "decisions": ["skipped", "skipped", "hold", "skipped", "insufficient_data"],
      "dates":     ["2026-04-19", "2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23"],
      "alerted": true
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_THRESHOLD = 3
DEFAULT_REPORTS_DIR = Path("artifacts/reports")
NON_PROGRESSING = {"skipped", "insufficient_data", "hold"}
_REPORT_RE = re.compile(r"f2_promotion_gate_(\d{4}-\d{2}-\d{2})\.json$")


def _scan_reports(reports_dir: Path) -> list[tuple[str, str]]:
    """Return [(date, decision)] sorted ascending by date.

    A report file with a missing or unreadable ``decision`` field is
    treated as ``skipped`` so we still detect "broken-but-failing"
    streaks.
    """
    if not reports_dir.exists():
        return []
    rows: list[tuple[str, str]] = []
    for path in reports_dir.iterdir():
        m = _REPORT_RE.search(path.name)
        if not m:
            continue
        date = m.group(1)
        decision = "skipped"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                decision = str(data.get("decision") or "skipped")
        except (OSError, ValueError):
            decision = "skipped"
        rows.append((date, decision))
    rows.sort(key=lambda r: r[0])
    return rows


def _trailing_streak(rows: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """Return (dates, decisions) of the longest trailing non-progressing run."""
    dates: list[str] = []
    decisions: list[str] = []
    for date, decision in reversed(rows):
        if decision in NON_PROGRESSING:
            dates.append(date)
            decisions.append(decision)
        else:
            break
    dates.reverse()
    decisions.reverse()
    return dates, decisions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect skipped/insufficient_data/hold streaks on the F2 "
            "promotion gate and emit a GitHub Actions ::warning::."
        )
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help=f"Directory holding f2_promotion_gate_*.json (default: {DEFAULT_REPORTS_DIR}).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=(
            "Trailing non-progressing run length that triggers the alert "
            f"(default: {DEFAULT_THRESHOLD})."
        ),
    )
    args = parser.parse_args(argv)

    if args.threshold < 1:
        print("ERROR: --threshold must be >= 1", file=sys.stderr)
        return 1

    rows = _scan_reports(args.reports_dir)
    dates, decisions = _trailing_streak(rows)
    streak = len(decisions)
    alerted = streak >= args.threshold

    if alerted:
        # GitHub Actions ::warning:: annotations are surfaced in the
        # run summary AND in the file-changes pane of the PR if
        # applicable, without failing the workflow.
        breakdown = ",".join(decisions)
        first_date = dates[0] if dates else "?"
        last_date = dates[-1] if dates else "?"
        print(
            f"::warning title=f2-promotion-gate-stalled::"
            f"streak={streak} threshold={args.threshold} "
            f"first={first_date} last={last_date} decisions={breakdown}",
            file=sys.stderr,
        )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "reports_dir": str(args.reports_dir),
        "threshold": args.threshold,
        "streak": streak,
        "dates": dates,
        "decisions": decisions,
        "alerted": alerted,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
