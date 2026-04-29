"""Plan 2.8 ledger status-run summary.

Enumerates every consecutive status run in insertion order.
Each entry captures the status, the first and last
``captured_at`` timestamp observed within the run, and the
run length in records.
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
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in VALID_STATUSES:
            continue
        ts = rec.get("captured_at")
        ts_val = ts if isinstance(ts, str) and ts else None
        if current is None or current["status"] != status:
            if current is not None:
                runs.append(current)
            current = {
                "status": status,
                "start":  ts_val,
                "end":    ts_val,
                "length": 1,
            }
        else:
            current["length"] += 1
            if ts_val is not None:
                current["end"] = ts_val
                if current["start"] is None:
                    current["start"] = ts_val
    if current is not None:
        runs.append(current)
    return {
        "schema_version": 1,
        "run_count":      len(runs),
        "entries":        runs,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 ledger status-run summary",
        "",
        f"- run_count: {report['run_count']}",
        "",
    ]
    if not report["entries"]:
        lines.extend(["_none_", ""])
    else:
        for e in report["entries"]:
            start = e["start"] if e["start"] is not None else "_unknown_"
            end = e["end"] if e["end"] is not None else "_unknown_"
            lines.append(
                f"  - {e['status']}: length={e['length']} "
                f"start={start} end={end}",
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enumerate consecutive status runs.",
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
