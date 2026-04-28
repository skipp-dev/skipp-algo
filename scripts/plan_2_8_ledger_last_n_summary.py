"""Plan 2.8 last-N ledger summary.

Returns status counts over only the most recent N records in
the ledger (after filtering invalid entries). ``--last-n 0``
means "all records". Useful for trailing-window health views.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = ("green", "amber", "red", "unknown")


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


def compute(records: list[dict[str, Any]], last_n: int) -> dict[str, Any]:
    cleaned: list[str] = []
    for rec in records:
        raw = rec.get("status")
        if not isinstance(raw, str):
            continue
        s = raw.strip().lower()
        if s in VALID_STATUSES:
            cleaned.append(s)
    window = cleaned if last_n <= 0 else cleaned[-last_n:]
    counts = {s: 0 for s in VALID_STATUSES}
    for s in window:
        counts[s] += 1
    return {
        "schema_version": 1,
        "last_n":         last_n,
        "window_size":    len(window),
        "total_records":  len(cleaned),
        "counts":         counts,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Plan 2.8 last-N summary",
        "",
        f"- last_n: {report['last_n']}",
        f"- window_size: {report['window_size']}",
        f"- total_records: {report['total_records']}",
        "",
        "| status | count |",
        "|---|---:|",
    ]
    for s in VALID_STATUSES:
        lines.append(f"| `{s}` | {report['counts'][s]} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Status counts for the last N records.",
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--last-n", type=int, default=10)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(_iter_records(args.ledger), args.last_n)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
