"""Plan 2.8 ledger green streak history.

Lists all contiguous runs of ``green`` status records in
chronological order. Each segment reports its 1-based index,
length, start_at, end_at, and duration in hours. Non-green
records close the current streak; invalid statuses or
malformed timestamps are skipped.
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


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    cur: list[tuple[datetime, str]] = []
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in VALID_STATUSES:
            continue
        ts = _parse(rec.get("captured_at"))
        if ts is None:
            continue
        if status == "green":
            cur.append((ts, rec.get("captured_at", "")))
        elif cur:
            segments.append(cur)
            cur = []
    if cur:
        segments.append(cur)

    entries: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments, start=1):
        first_ts, first_raw = seg[0]
        last_ts, last_raw = seg[-1]
        dur = (last_ts - first_ts).total_seconds() / 3600.0
        entries.append({
            "index":         idx,
            "length":        len(seg),
            "start_at":      first_raw,
            "end_at":        last_raw,
            "hours":         round(dur, 4),
        })
    return {
        "schema_version": 1,
        "segment_count":  len(entries),
        "entries":        entries,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 ledger green streak history",
        "",
        f"- segment_count: {report['segment_count']}",
        "",
    ]
    if not report["entries"]:
        lines.extend(["_none_", ""])
    else:
        for e in report["entries"]:
            lines.append(
                f"  - #{e['index']} len={e['length']} "
                f"{e['start_at']} .. {e['end_at']} "
                f"({e['hours']}h)"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="All past green-streak segments in order.",
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
