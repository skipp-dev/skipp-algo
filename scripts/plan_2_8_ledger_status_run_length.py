"""Plan 2.8 status run-length encoder.

Walks the ledger in order and produces a list of
``{status, length, start_at, end_at}`` segments describing
consecutive runs of the same status. Useful for spotting long
amber/red stretches that single-point views miss.
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
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in VALID_STATUSES:
            continue
        ts = rec.get("captured_at") if isinstance(
            rec.get("captured_at"), str,
        ) else None
        if current is None or current["status"] != status:
            if current is not None:
                segments.append(current)
            current = {
                "status":   status,
                "length":   1,
                "start_at": ts,
                "end_at":   ts,
            }
        else:
            current["length"] += 1
            current["end_at"] = ts
    if current is not None:
        segments.append(current)
    return {
        "schema_version": 1,
        "segment_count":  len(segments),
        "segments":       segments,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 status run lengths",
        "",
        f"- segment_count: {report['segment_count']}",
        "",
        "| status | length | start_at | end_at |",
        "|---|---:|---|---|",
    ]
    if report["segments"]:
        for s in report["segments"]:
            lines.append(
                f"| `{s['status']}` | {s['length']} | "
                f"`{s['start_at']}` | `{s['end_at']}` |",
            )
    else:
        lines.append("| _none_ | 0 | - | - |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run-length encode the ledger status series.",
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
