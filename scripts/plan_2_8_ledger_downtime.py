"""Plan 2.8 ledger downtime calculator.

Computes non-green *downtime* intervals by walking ledger
records in captured order. Each interval spans the time between
two consecutive records where the **earlier** record's status is
amber, red, or unknown; the interval ends at the timestamp of
the next record.

Trailing non-green intervals (no next record) are *not* counted,
since we can't bound them without a ``now``. Pure stdlib.
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

NON_GREEN = frozenset({"amber", "red", "unknown"})


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
    clean: list[tuple[_dt.datetime, str]] = []
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        raw = rec.get("status")
        if ts is None or not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in ("green", "amber", "red", "unknown"):
            continue
        clean.append((ts, status))
    intervals: list[dict[str, Any]] = []
    totals = {"amber": 0.0, "red": 0.0, "unknown": 0.0}
    for (t0, s0), (t1, _) in pairwise(clean):
        if s0 not in NON_GREEN:
            continue
        secs = (t1 - t0).total_seconds()
        if secs < 0:
            secs = 0.0
        totals[s0] += secs
        intervals.append({
            "status":   s0,
            "start":    t0.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "end":      t1.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "seconds":  secs,
        })
    total_secs = sum(totals.values())
    return {
        "schema_version": 1,
        "counts": {
            "intervals": len(intervals),
            "total_seconds": total_secs,
        },
        "by_status": totals,
        "intervals": intervals,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 ledger downtime",
        "",
        f"- intervals:     {report['counts']['intervals']}",
        f"- total seconds: {report['counts']['total_seconds']:.0f}",
        "",
        "| status | seconds |",
        "| --- | --- |",
    ]
    for s in ("amber", "red", "unknown"):
        lines.append(f"| {s} | {report['by_status'][s]:.0f} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute non-green downtime from the status ledger.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="json")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    records = _iter_records(args.ledger)
    report = compute(records)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
