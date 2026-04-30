"""Plan 2.8 ledger longest-streak calculator.

Walks the ledger records in chronological order and reports the
longest consecutive run of each status, with start/end captured_at
and length (number of records).
"""

from __future__ import annotations

import argparse
import json
import sys
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


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    longest: dict[str, dict[str, Any]] = {
        s: {"length": 0, "start": None, "end": None}
        for s in VALID_STATUSES
    }
    cur_status: str | None = None
    cur_length = 0
    cur_start: str | None = None
    cur_end: str | None = None

    def _commit() -> None:
        if cur_status is None or cur_length == 0:
            return
        if cur_length > longest[cur_status]["length"]:
            longest[cur_status] = {
                "length": cur_length,
                "start":  cur_start,
                "end":    cur_end,
            }

    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s not in VALID_STATUSES:
            continue
        ts = rec.get("captured_at")
        if s != cur_status:
            _commit()
            cur_status = s
            cur_length = 1
            cur_start = ts if isinstance(ts, str) else None
            cur_end = cur_start
        else:
            cur_length += 1
            if isinstance(ts, str):
                cur_end = ts
    _commit()

    return {
        "schema_version": 1,
        "longest":        longest,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Plan 2.8 longest streaks", ""]
    for status in ("green", "amber", "red", "unknown"):
        entry = report["longest"][status]
        lines.append(f"## {status}")
        lines.append(f"- length: {entry['length']}")
        lines.append(f"- start:  {entry['start'] or 'n/a'}")
        lines.append(f"- end:    {entry['end'] or 'n/a'}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute longest consecutive streak per status.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="json")
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
