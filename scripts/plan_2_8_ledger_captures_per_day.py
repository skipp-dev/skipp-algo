"""Plan 2.8 ledger captures per day.

Groups ledger records by UTC calendar day and reports the
capture count per day. Invalid statuses and malformed
timestamps are silently skipped. ``days`` is sorted ascending.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


def _iter_records(ledger: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not ledger.exists():
        return out
    for line in ledger.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _day(ts: Any) -> str | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts).date().isoformat()
    except ValueError:
        return None


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        if raw.strip().lower() not in VALID_STATUSES:
            continue
        d = _day(rec.get("captured_at"))
        if d is None:
            continue
        counts[d] = counts.get(d, 0) + 1
    days = sorted(counts.keys())
    return {
        "schema_version": 1,
        "distinct_days":  len(days),
        "total_captures": sum(counts.values()),
        "per_day": [{"day": d, "count": counts[d]} for d in days],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 ledger captures per day",
        "",
        f"- distinct_days: {report['distinct_days']}",
        f"- total_captures: {report['total_captures']}",
        "",
    ]
    if not report["per_day"]:
        lines.extend(["_none_", ""])
    else:
        for e in report["per_day"]:
            lines.append(f"  - {e['day']}: {e['count']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ledger capture counts grouped by UTC date.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(_iter_records(args.ledger))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
