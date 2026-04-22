"""Plan 2.8 weekly summary trailing-uppercase-line count.

Counts non-empty lines whose last character is an ASCII uppercase
letter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compute(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    cnt = sum(
        1 for ln in lines
        if ln and ln[-1].isascii() and ln[-1].isupper()
    )
    return {
        "schema_version":                  1,
        "line_count":                      len(lines),
        "trailing_uppercase_line_count":   cnt,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary trailing uppercase line count\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        "- trailing_uppercase_line_count: "
        f"{report['trailing_uppercase_line_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Trailing-uppercase line count.",
    )
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
