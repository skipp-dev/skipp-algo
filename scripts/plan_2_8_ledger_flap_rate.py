"""Plan 2.8 ledger flap-rate calculator.

Counts status transitions (flips) grouped by ISO week of the *to*
record. Reports total flips, the number of weeks covered, and the
average flips-per-week over the observed weeks.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


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


def _bucket(ts: _dt.datetime) -> str:
    iso = ts.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned: list[tuple[_dt.datetime, str]] = []
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        raw = rec.get("status")
        if ts is None or not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s not in VALID_STATUSES:
            continue
        cleaned.append((ts, s))
    per_week: dict[str, int] = {}
    flips = 0
    for (_, prev_s), (ts, cur_s) in pairwise(cleaned):
        if prev_s != cur_s:
            flips += 1
            key = _bucket(ts)
            per_week[key] = per_week.get(key, 0) + 1
    weeks_covered = len(per_week)
    avg = flips / weeks_covered if weeks_covered else 0.0
    rows = [
        {"week": k, "flips": v}
        for k, v in sorted(per_week.items())
    ]
    return {
        "schema_version": 1,
        "total_flips":    flips,
        "weeks_covered":  weeks_covered,
        "flips_per_week": round(avg, 2),
        "weeks":          rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 flap rate",
        "",
        f"- total flips:    {report['total_flips']}",
        f"- weeks covered:  {report['weeks_covered']}",
        f"- flips / week:   {report['flips_per_week']:.2f}",
        "",
        "| week | flips |",
        "|---|---:|",
    ]
    if report["weeks"]:
        for w in report["weeks"]:
            lines.append(f"| {w['week']} | {w['flips']} |")
    else:
        lines.append("| _no flips_ | 0 |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count status flips per ISO week.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-flips", action="store_true")
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
    if args.fail_on_flips and report["total_flips"] > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
