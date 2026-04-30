"""Plan 2.8 ledger green index mean.

Arithmetic mean of zero-based indices (among valid records) of
``green`` observations. NaN -> 0.0 if no greens.
"""

from __future__ import annotations

import argparse
import json
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
    total = 0
    indices: list[int] = []
    for rec in records:
        status = rec.get("status")
        if status not in VALID_STATUSES:
            continue
        if status == "green":
            indices.append(total)
        total += 1
    mean = 0.0
    if indices:
        mean = round(sum(indices) / len(indices), 6)
    return {
        "schema_version":       1,
        "record_count":         total,
        "green_count":          len(indices),
        "green_index_mean":     mean,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 ledger green index mean\n"
        "\n"
        f"- record_count: {report['record_count']}\n"
        f"- green_count: {report['green_count']}\n"
        f"- green_index_mean: {report['green_index_mean']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Green index mean.")
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
