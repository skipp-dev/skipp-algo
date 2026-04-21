"""Plan 2.8 ledger null value count.

Counts the number of ``None`` / JSON ``null`` values appearing as the
value of any top-level field across all ledger records. Only records
that parse as JSON objects are inspected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(path: Path) -> dict[str, Any]:
    records = 0
    nulls = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        records += 1
        nulls += sum(1 for v in obj.values() if v is None)
    return {
        "schema_version":       1,
        "record_count":         records,
        "null_value_count":     nulls,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 ledger null value count\n"
        "\n"
        f"- record_count: {report['record_count']}\n"
        f"- null_value_count: {report['null_value_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Null value count.")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    report = compute(args.ledger)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
