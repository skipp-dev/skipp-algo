"""Plan 2.8 ledger month-summary.

Groups ledger records by calendar month (``YYYY-MM``) and reports
per-month counts per status (green / amber / red / unknown) plus
a total. Emits JSON or a small markdown table.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = ("green", "amber", "red", "unknown")


def _parse_ts(raw: Any) -> _dt.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, int]] = {}
    skipped = 0
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        raw = rec.get("status")
        if ts is None or not isinstance(raw, str):
            skipped += 1
            continue
        s = raw.strip().lower()
        if s not in VALID_STATUSES:
            skipped += 1
            continue
        key = ts.strftime("%Y-%m")
        slot = buckets.setdefault(key, {k: 0 for k in VALID_STATUSES})
        slot[s] += 1
    months: list[dict[str, Any]] = []
    for key in sorted(buckets):
        slot = buckets[key]
        total = sum(slot.values())
        months.append({
            "month":   key,
            "total":   total,
            **slot,
        })
    return {
        "schema_version": 1,
        "months":          months,
        "skipped":         skipped,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 month summary",
        "",
        "| month | total | green | amber | red | unknown |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    if report["months"]:
        for m in report["months"]:
            lines.append(
                f"| {m['month']} | {m['total']} | {m['green']} "
                f"| {m['amber']} | {m['red']} | {m['unknown']} |"
            )
    else:
        lines.append("| _no records_ | 0 | 0 | 0 | 0 | 0 |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Per-calendar-month ledger status counts.",
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
