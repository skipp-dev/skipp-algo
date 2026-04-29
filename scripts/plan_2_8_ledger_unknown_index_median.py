"""Plan 2.8 ledger unknown index median."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

VALID_STATUSES = frozenset({"green", "amber", "red", "unknown"})


def _iter(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def compute(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    statuses = [r.get("status") for r in records
                if r.get("status") in VALID_STATUSES]
    us = [i for i, s in enumerate(statuses) if s == "unknown"]
    median = round(statistics.median(us), 6) if us else -1.0
    return {
        "schema_version":       1,
        "record_count":         len(statuses),
        "unknown_index_median": median,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 ledger unknown index median\n"
        "\n"
        f"- record_count: {report['record_count']}\n"
        f"- unknown_index_median: {report['unknown_index_median']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unknown index median.")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(_iter(args.ledger))
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
