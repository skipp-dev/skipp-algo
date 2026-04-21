"""Plan 2.8 weekly summary grave char count.

Counts ASCII grave accent (backtick-like U+0060) characters in
the summary. Distinct from ``backtick_char_count`` which already
exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version":       1,
            "char_count":           0,
            "grave_char_count":     0,
        }
    text = path.read_text(encoding="utf-8")
    return {
        "schema_version":       1,
        "char_count":           len(text),
        "grave_char_count":     sum(1 for c in text if c == "\u0060"),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary grave char count\n"
        "\n"
        f"- char_count: {report['char_count']}\n"
        f"- grave_char_count: {report['grave_char_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grave char count.")
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
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
