"""Plan 2.8 weekly summary sentence count.

Sentence count: number of terminator chars ``.`` / ``!`` /
``?`` in the summary file. Missing or empty file -> 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

_TERMS = set(".!?")


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":   1,
            "char_count":       0,
            "sentence_count":   0,
        }
    text = path.read_text(encoding="utf-8")
    count = sum(1 for ch in text if ch in _TERMS)
    return {
        "schema_version":   1,
        "char_count":       len(text),
        "sentence_count":   count,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary sentence count\n"
        "\n"
        f"- char_count: {report['char_count']}\n"
        f"- sentence_count: {report['sentence_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sentence count.")
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
