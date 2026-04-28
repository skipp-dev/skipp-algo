"""Plan 2.8 weekday histogram.

Counts ledger records per UTC weekday (Mon=0..Sun=6). Empty
weekdays are surfaced so cron gaps (e.g. a workflow that never
runs on weekends) are visible at a glance.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


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
    buckets = [0] * 7
    skipped = 0
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        if ts is None:
            skipped += 1
            continue
        buckets[ts.astimezone(_dt.UTC).weekday()] += 1
    empty = [WEEKDAY_NAMES[i] for i, n in enumerate(buckets) if n == 0]
    return {
        "schema_version": 1,
        "total":          sum(buckets),
        "buckets":        buckets,
        "empty_weekdays": empty,
        "skipped":        skipped,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 weekday histogram",
        "",
        f"- total:          {report['total']}",
        f"- empty_weekdays: {len(report['empty_weekdays'])}/7",
        "",
        "| weekday | count |",
        "|---|---:|",
    ]
    for i, name in enumerate(WEEKDAY_NAMES):
        lines.append(f"| {name} | {report['buckets'][i]} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Per-UTC-weekday record histogram.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-empty-weekdays", type=int, default=None)
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
    if args.fail_on_empty_weekdays is not None \
            and len(report["empty_weekdays"]) > args.fail_on_empty_weekdays:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
