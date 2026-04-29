"""Plan 2.8 weekly rollup.

Emits a compact one-screen markdown summary for the latest week,
pulling from the ledger and optionally the snooze-expiry /
size-budget reports. Pure stdlib.
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

VALID_STATUSES = ("green", "amber", "red", "unknown")


def _parse_ts(raw: Any) -> _dt.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_ledger(ledger: Path) -> list[dict[str, Any]]:
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


def summarise(
    records: list[dict[str, Any]], *,
    weeks: int = 1,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    now_ = now or _dt.datetime.now(tz=_dt.UTC)
    cutoff = now_ - _dt.timedelta(weeks=weeks)
    in_window: list[tuple[_dt.datetime, str]] = []
    for rec in records:
        ts = _parse_ts(rec.get("captured_at"))
        raw = rec.get("status")
        if ts is None or not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in VALID_STATUSES:
            continue
        if ts >= cutoff:
            in_window.append((ts, status))
    flips = sum(
        1 for (_, a), (_, b) in pairwise(in_window) if a != b
    )
    counts = {s: sum(1 for _, st in in_window if st == s)
              for s in VALID_STATUSES}
    latest = in_window[-1][1] if in_window else None
    return {
        "schema_version": 1,
        "weeks":    weeks,
        "counts":   counts,
        "total":    len(in_window),
        "flips":    flips,
        "latest":   latest,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Plan 2.8 weekly rollup (last {report['weeks']} wk)",
        "",
        f"- latest status: {report['latest'] or '-'}",
        f"- observations:  {report['total']}",
        f"- flips:         {report['flips']}",
        "",
        "| status | count |",
        "| --- | --- |",
    ]
    for s in VALID_STATUSES:
        lines.append(f"| {s} | {report['counts'][s]} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compact per-week rollup from the status ledger.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--weeks", type=int, default=1)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1
    if args.weeks < 1:
        print("ERROR: --weeks must be >= 1", file=sys.stderr)
        return 1

    records = _load_ledger(args.ledger)
    report = summarise(records, weeks=args.weeks)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
