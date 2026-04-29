"""Plan 2.8 ledger average run length.

Reports the arithmetic mean length of consecutive status
runs across the ledger. Rounded to two decimals. Records
with invalid statuses are skipped.
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
    lengths: list[int] = []
    cur_status: str | None = None
    cur_length = 0
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        status = raw.strip().lower()
        if status not in VALID_STATUSES:
            continue
        if cur_status != status:
            if cur_status is not None:
                lengths.append(cur_length)
            cur_status = status
            cur_length = 1
        else:
            cur_length += 1
    if cur_status is not None:
        lengths.append(cur_length)
    if not lengths:
        return {
            "schema_version": 1,
            "run_count":      0,
            "total_records":  0,
            "avg_length":     0.0,
        }
    return {
        "schema_version": 1,
        "run_count":      len(lengths),
        "total_records":  sum(lengths),
        "avg_length":     round(sum(lengths) / len(lengths), 2),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 ledger average run length\n"
        "\n"
        f"- run_count: {report['run_count']}\n"
        f"- total_records: {report['total_records']}\n"
        f"- avg_length: {report['avg_length']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mean length of consecutive status runs.",
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
