"""Plan 2.8 ledger record byte size mean.

Mean byte length (UTF-8) of non-blank ledger lines.
Missing or empty ledger yields 0.0.
"""

from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(path: Path) -> dict[str, Any]:
    sizes: list[int] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            sizes.append(len(line.encode("utf-8")))
    mean = (sum(sizes) / len(sizes)) if sizes else 0.0
    return {
        "schema_version":           1,
        "record_count":             len(sizes),
        "record_byte_size_mean":    round(mean, 4),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 ledger record byte size mean\n"
        "\n"
        f"- record_count: {report['record_count']}\n"
        "- record_byte_size_mean: "
        f"{report['record_byte_size_mean']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record byte size.")
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
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
