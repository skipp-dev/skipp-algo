"""Plan 2.8 weekly summary average word length.

Mean word length (whitespace split) across the file.
Missing or empty file yields 0.0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":    1,
            "word_count":        0,
            "avg_word_length":   0.0,
        }
    tokens = path.read_text(encoding="utf-8").split()
    avg = sum(len(t) for t in tokens) / len(tokens) if tokens else 0.0
    return {
        "schema_version":    1,
        "word_count":        len(tokens),
        "avg_word_length":   round(avg, 4),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary avg word length\n"
        "\n"
        f"- word_count: {report['word_count']}\n"
        f"- avg_word_length: {report['avg_word_length']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Avg word length.")
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
