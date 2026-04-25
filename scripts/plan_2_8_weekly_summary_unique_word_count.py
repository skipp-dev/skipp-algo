"""Plan 2.8 weekly summary unique word count.

Number of distinct case-folded, whitespace-split tokens.
Missing or empty file yields 0.
"""

from __future__ import annotations

from scripts.smc_atomic_write import atomic_write_text

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":      1,
            "line_count":          0,
            "unique_word_count":   0,
        }
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    unique = {tok.casefold() for tok in text.split()}
    return {
        "schema_version":      1,
        "line_count":          len(lines),
        "unique_word_count":   len(unique),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary unique word count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        f"- unique_word_count: {report['unique_word_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unique word count.")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.exists():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = compute(args.summary)
    body = render_markdown(report) if args.format == "md" \
        else json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
