"""Plan 2.8 weekly summary max line length.

Reports the longest character length across all lines.
Missing or empty file yields 0.
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
            "schema_version":   1,
            "line_count":       0,
            "max_line_length":  0,
        }
    lengths = [
        len(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    return {
        "schema_version":   1,
        "line_count":       len(lengths),
        "max_line_length":  max(lengths) if lengths else 0,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# Plan 2.8 weekly summary max line length\n"
        "\n"
        f"- line_count: {report['line_count']}\n"
        f"- max_line_length: {report['max_line_length']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Max line length.")
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
