"""Plan 2.8 ledger byte size per line mean."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def compute(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    lines = [ln for ln in data.splitlines() if ln.strip() != b""]
    total = sum(len(ln) for ln in lines)
    mean = (total / len(lines)) if lines else 0.0
    return {
        "schema_version":               1,
        "nonblank_line_count":          len(lines),
        "byte_size_per_line_mean":      round(mean, 4),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 ledger byte size per line mean\n"
        "\n"
        f"- nonblank_line_count: {report['nonblank_line_count']}\n"
        "- byte_size_per_line_mean: "
        f"{report['byte_size_per_line_mean']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mean bytes per line.")
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
