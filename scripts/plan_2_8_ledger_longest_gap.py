"""Plan 2.8 ledger longest gap.

Reports the longest gap (in hours) between consecutive
captured_at timestamps in the ledger. Malformed timestamps
are skipped. When fewer than two valid timestamps are
present, ``found`` is ``False``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from itertools import pairwise
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


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    times: list[tuple[datetime, str]] = []
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        if raw.strip().lower() not in VALID_STATUSES:
            continue
        ts = _parse(rec.get("captured_at"))
        if ts is not None:
            times.append((ts, rec.get("captured_at", "")))
    if len(times) < 2:
        return {"schema_version": 1, "found": False}
    longest = 0.0
    start = times[0][1]
    end = times[0][1]
    for prev, cur in pairwise(times):
        delta = (cur[0] - prev[0]).total_seconds() / 3600.0
        if delta > longest:
            longest = delta
            start = prev[1]
            end = cur[1]
    return {
        "schema_version": 1,
        "found":          True,
        "longest_hours":  round(longest, 4),
        "start_at":       start,
        "end_at":         end,
    }


def render_markdown(report: dict[str, Any]) -> str:
    if not report.get("found"):
        return "# Plan 2.8 ledger longest gap\n\n_none_\n"
    return (
        "# Plan 2.8 ledger longest gap\n"
        "\n"
        f"- longest_hours: {report['longest_hours']}\n"
        f"- start_at: {report['start_at']}\n"
        f"- end_at: {report['end_at']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Longest gap between consecutive captures.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--fail-above-hours", type=float, default=None)
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
    if (args.fail_above_hours is not None
            and report.get("found")
            and report["longest_hours"] > args.fail_above_hours):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
